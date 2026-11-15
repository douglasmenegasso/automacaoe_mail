"""Automação principal: lê e-mails do Gmail, classifica com IA e age.

Ações por categoria:
- spam_propaganda -> apaga (ou move para Lixeira/Arquiva, conforme config)
- responde_se     -> envia resposta automática (se auto_reply_enabled = true)
- precisa_humano  -> envia alerta por WhatsApp com resumo do e-mail

Uso:
    python main.py            # processa a caixa de entrada
    python main.py --dry-run  # analisa mas NÃO executa ações (recomendado p/ começar)
"""
import argparse
import base64
import sys
from email.mime.text import MIMEText

import gmail_client
from analyzer import classify_email
from settings import load_config
from whatsapp_notifier import send_whatsapp


def fetch_inbox_messages(service, query: str, max_results: int) -> list[dict]:
    resp = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    return resp.get("messages", [])


def get_message_full(service, msg_id: str) -> dict:
    return (
        service.users()
        .messages()
        .get(userId="me", id=msg_id, format="full")
        .execute()
    )


def delete_message(service, msg_id: str):
    service.users().messages().trash(userId="me", id=msg_id).execute()


def archive_message(service, msg_id: str):
    service.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ["INBOX", "UNREAD"]}
    ).execute()


def send_reply(service, email_data: dict, reply_text: str) -> bool:
    """Responde mantendo a mesma thread/assunto."""
    reply = MIMEText(reply_text, "plain", "utf-8")
    reply["To"] = _extract_address(email_data["from"])
    reply["Subject"] = (
        email_data["subject"]
        if email_data["subject"].lower().startswith("re:")
        else f"Re: {email_data['subject']}"
    )
    raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()
    try:
        service.users().messages().send(
            userId="me",
            body={"raw": raw, "threadId": email_data["thread_id"]},
        ).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[ERRO] Falha ao enviar resposta: {exc}")
        return False


def _extract_address(from_header: str) -> str:
    """'Nome <a@b.com>' -> 'a@b.com'."""
    if "<" in from_header and ">" in from_header:
        return from_header[from_header.index("<") + 1 : from_header.index(">")]
    return from_header.strip()


def process(dry_run: bool = False):
    config = load_config()
    gcfg = config["gmail"]
    acfg = config["automation"]
    model = config["openai"]["model"]

    print("[1/3] Conectando ao Gmail...")
    service = gmail_client.build_service()

    print("[2/3] Listando e-mails da caixa de entrada...")
    ids = fetch_inbox_messages(service, gcfg.get("query", "in:inbox"),
                               gcfg.get("max_emails_per_run", 50))
    print(f"      {len(ids)} e-mail(s) para analisar.\n")

    stats = {"spam": 0, "respondido": 0, "alertado": 0, "erro": 0}
    alerts = []  # acumula avisos p/ mandar 1 WhatsApp resumido

    for i, ref in enumerate(ids, 1):
        msg = get_message_full(service, ref["id"])
        data = gmail_client.extract_email_data(msg)
        analysis = classify_email(data, model=model)
        cat = analysis["categoria"]

        print(f"--- [{i}/{len(ids)}] DE: {data['from']}")
        print(f"    ASSUNTO: {data['subject']}")
        print(f"    CATEGORIA: {cat} | MOTIVO: {analysis['motivo']}")

        if dry_run:
            print("    [DRY-RUN] nenhuma ação executada.\n")
            continue

        try:
            if cat == "spam_propaganda":
                if acfg.get("auto_delete_spam", True):
                    delete_message(service, data["id"])
                    print("    => APAGADO (lixeira)")
                else:
                    archive_message(service, data["id"])
                    print("    => ARQUIVADO")
                stats["spam"] += 1

            elif cat == "responde_se" and analysis.get("resposta"):
                if acfg.get("auto_reply_enabled", False):
                    ok = send_reply(service, data, analysis["resposta"])
                    print(f"    => RESPOSTA AUTOMÁTICA {'ENVIADA' if ok else 'FALHOU'}")
                    if ok:
                        stats["respondido"] += 1
                        archive_message(service, data["id"])
                else:
                    print("    => Resposta gerada, mas auto_reply_enabled=false; só arquivando.")
                    archive_message(service, data["id"])

            elif cat == "precisa_humano":
                resumo = analysis.get("resumo_para_whatsapp") or f"{data['from']} - {data['subject']}"
                alerts.append(f"• De: {data['from']}\n  Assunto: {data['subject']}\n  {resumo}")
                # marca como lida para não reprocessar no próximo ciclo
                service.users().messages().modify(
                    userId="me", id=data["id"], body={"removeLabelIds": ["UNREAD"]}
                ).execute()
                stats["alertado"] += 1
                print("    => ALERTA separado para WhatsApp")

        except Exception as exc:  # noqa: BLE001
            print(f"    [ERRO] {exc}")
            stats["erro"] += 1
        print()

    # Envia UM único WhatsApp consolidado com todos os assuntos que precisam do usuário
    if alerts and not dry_run:
        body = "📬 *E-mails que precisam da sua atenção:*\n\n" + "\n\n".join(alerts)
        send_whatsapp(config, body)

    print("=" * 50)
    print(f"RESUMO: apagados/arquivados={stats['spam']} | respondidos={stats['respondido']} | "
          f"alertados via WhatsApp={stats['alertado']} | erros={stats['erro']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automação de e-mail Gmail + WhatsApp")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analisa os e-mails sem apagar/responder/notificar")
    args = parser.parse_args()
    try:
        process(dry_run=args.dry_run)
    except FileNotFoundError as exc:
        sys.exit(str(exc))
