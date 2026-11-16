"""Orquestra a automação: ler Gmail -> classificar (IA com failover) -> agir -> notificar.

Uso:
    python main.py            # executa de verdade
    python main.py --dry-run  # simula: nao apaga, nao responde, nao etiqueta nada
"""
import base64
import sys
from email.mime.text import MIMEText

from googleapiclient.errors import HttpError

import settings
from analyzer import classify_email
from gmail_client import build_service, extract_email_data
from whatsapp_notifier import send_whatsapp

LABEL_NOME = "AutoMail"


def _get_or_create_label(service) -> str:
    resp = service.users().labels().list(userId="me").execute()
    for lb in resp.get("labels", []):
        if lb["name"].lower() == LABEL_NOME.lower():
            return lb["id"]
    novo = service.users().labels().create(
        userId="me",
        body={"name": LABEL_NOME, "labelListVisibility": "labelShow",
              "messageListVisibility": "show"},
    ).execute()
    print(f"[GMAIL] Label {LABEL_NOME} criada.")
    return novo["id"]


def _apply_label(service, msg_id: str, label_id: str):
    service.users().messages().modify(
        userId="me", id=msg_id, body={"addLabelIds": [label_id]}).execute()


def _header(msg: dict, nome: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == nome.lower():
            return h["value"]
    return ""


def _send_reply(service, data: dict, msg: dict, texto: str, de_email: str):
    """Responde na MESMA thread do e-mail original."""
    message_id = _header(msg, "Message-ID")
    assunto = data["subject"]
    if not assunto.lower().startswith("re:"):
        assunto = f"Re: {assunto}"
    mime = MIMEText(texto, "plain", "utf-8")
    mime["To"] = data["from"]
    mime["From"] = de_email
    mime["Subject"] = assunto
    mime["In-Reply-To"] = message_id
    mime["References"] = message_id
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": data["thread_id"]}
    ).execute()


def run(dry_run: bool):
    cfg = settings.load_config()
    service = build_service()
    gcfg = cfg["gmail"]
    label_id = None if dry_run else _get_or_create_label(service)

    query = f"{gcfg.get('query', 'in:inbox')} -label:{LABEL_NOME}"
    resp = service.users().messages().list(
        userId="me", q=query, maxResults=int(gcfg.get("max_emails_per_run", 50))
    ).execute()
    itens = resp.get("messages", [])
    print(f"[GMAIL] {len(itens)} e-mail(s) novos para analisar.")

    cont = {"spam_propaganda": 0, "responde_se": 0, "precisa_humano": 0,
            "acoes": 0, "erros": 0}

    for item in itens:
        try:
            msg = service.users().messages().get(
                userId="me", id=item["id"], format="full").execute()
            data = extract_email_data(msg)
            resultado = classify_email(data, cfg)
            cat = resultado["categoria"]
            cont[cat] += 1
            print(f"\n--- De: {data['from']} | Assunto: {data['subject']}")
            print(f"    categoria: {cat} | motivo: {resultado['motivo']}")

            if dry_run:
                print("    [DRY-RUN] nenhuma acao executada.")
                continue

            if cat == "spam_propaganda":
                if cfg["automation"].get("auto_delete_spam"):
                    service.users().messages().trash(
                        userId="me", id=data["id"]).execute()
                    print("    -> movido para a LIXEIRA (recuperavel por 30 dias)")
                    cont["acoes"] += 1
                else:
                    print("    -> spam, mas auto_delete_spam=false: so etiquetado")
            elif cat == "responde_se":
                if cfg["automation"].get("auto_reply_enabled") and resultado.get("resposta"):
                    _send_reply(service, data, msg, resultado["resposta"],
                                cfg["automation"].get("notify_email", ""))
                    print("    -> resposta automatica enviada na thread")
                    cont["acoes"] += 1
                else:
                    print("    -> responde_se, mas resposta automatica desativada")
            else:  # precisa_humano
                aviso = (
                    f"🙋 PRECISA DE VOCE\n"
                    f"De: {data['from']}\n"
                    f"Assunto: {data['subject']}\n"
                    f"{resultado.get('resumo_para_whatsapp') or resultado['motivo']}"
                )
                if send_whatsapp(cfg, aviso):
                    cont["acoes"] += 1
                else:
                    print("    [AVISO] falha ao notificar WhatsApp")

            _apply_label(service, data["id"], label_id)
        except HttpError as exc:
            cont["erros"] += 1
            print(f"    [ERRO] Gmail: {exc}")
        except Exception as exc:  # noqa: BLE001
            cont["erros"] += 1
            print(f"    [ERRO] inesperado: {exc}")

    print("\n===== RESUMO DA EXECUCAO =====")
    print(f"spam_propaganda: {cont['spam_propaganda']} | "
          f"responde_se: {cont['responde_se']} | "
          f"precisa_humano: {cont['precisa_humano']}")
    print(f"acoes executadas: {cont['acoes']} | erros: {cont['erros']}")
    print(f"modo: {'DRY-RUN (nada foi alterado)' if dry_run else 'PRODUCAO'}")


if __name__ == "__main__":
    run("--dry-run" in sys.argv)
