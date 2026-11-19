"""Orquestra a automação: ler Gmail -> classificar (IA com failover) -> agir -> notificar.

Uso:
    python main.py            # executa de verdade
    python main.py --dry-run  # simula: nao apaga, nao responde, nao etiqueta nada
"""
import base64
import sys
import time
from email.mime.text import MIMEText

from googleapiclient.errors import HttpError

import settings
from analyzer import classify_email
from gmail_client import build_service, extract_email_data
from whatsapp_notifier import send_whatsapp

LABEL_NOME = "AutoMail"


def _get_or_create_label_path(service, label_path: str) -> str:
    """Garante que o label (e seus pais, se houver '/') exista e retorna o ID."""
    resp = service.users().labels().list(userId="me").execute()
    existing = {lb["name"].lower(): lb["id"] for lb in resp.get("labels", [])}
    
    if label_path.lower() in existing:
        return existing[label_path.lower()]
    
    # Se for subpasta (ex: AutoMail/Spam), garante que o pai (AutoMail) exista primeiro
    if "/" in label_path:
        parent_name = label_path.split("/")[0]
        if parent_name.lower() not in existing:
            service.users().labels().create(
                userId="me",
                body={"name": parent_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
            ).execute()
            
    # Cria o label final (o Gmail entende a barra '/' e aninha automaticamente)
    novo = service.users().labels().create(
        userId="me",
        body={"name": label_path, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    ).execute()
    print(f"[GMAIL] Label '{label_path}' criada.")
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
    pausa = cfg.get("ai", {}).get("pausa_entre_emails", 4)

    query = f"{gcfg.get('query', 'in:inbox')} -label:{LABEL_NOME}"
    resp = service.users().messages().list(
        userId="me", q=query, maxResults=int(gcfg.get("max_emails_per_run", 50))
    ).execute()
    itens = resp.get("messages", [])
    print(f"[GMAIL] {len(itens)} e-mail(s) novos para analisar.")

    cont = {"spam_propaganda": 0, "responde_se": 0, "precisa_humano": 0,
            "acoes": 0, "erros": 0}

    for idx, item in enumerate(itens):
        try:
            msg = service.users().messages().get(
                userId="me", id=item["id"], format="full").execute()
            data = extract_email_data(msg)
            resultado = classify_email(data, cfg)
            cat = resultado["categoria"]
            cont[cat] += 1
            print(f"\n--- De: {data['from']} | Assunto: {data['subject']}")
            print(f"    categoria: {cat} | motivo: {resultado['motivo']}")

            # Define qual subpasta será usada
            if cat == "spam_propaganda":
                label_alvo = "AutoMail/Spam"
            elif cat == "responde_se":
                label_alvo = "AutoMail/Respostas"
            else:  # precisa_humano
                pasta_sugerida = resultado.get("pasta_sugerida", "").strip()
                if pasta_sugerida:
                    # Limpa o nome sugerido para evitar erros na API do Gmail
                    pasta_limpa = "".join(c for c in pasta_sugerida if c.isalnum() or c in (' ', '-', '_')).strip()
                    label_alvo = f"AutoMail/{pasta_limpa}"
                else:
                    label_alvo = "AutoMail/Atencao"

            if dry_run:
                print(f"    [DRY-RUN] seria movido para: {label_alvo}")
            else:
                if cat == "spam_propaganda":
                    if cfg["automation"].get("auto_delete_spam"):
                        service.users().messages().trash(
                            userId="me", id=data["id"]).execute()
                        print(f"    -> movido para a LIXEIRA e etiquetado como {label_alvo}")
                        cont["acoes"] += 1
                    else:
                        print(f"    -> spam, auto_delete_spam=false: apenas etiquetado em {label_alvo}")
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
                
                # Aplica a sub-etiqueta específica
                label_id_alvo = _get_or_create_label_path(service, label_alvo)
                _apply_label(service, data["id"], label_id_alvo)
        except HttpError as exc:
            cont["erros"] += 1
            print(f"    [ERRO] Gmail: {exc}")
        except Exception as exc:  # noqa: BLE001
            cont["erros"] += 1
            print(f"    [ERRO] inesperado: {exc}")

        if idx < len(itens) - 1:
            time.sleep(pausa)  # ritmo constante: nao estoura o limite por minuto

    print("\n===== RESUMO DA EXECUCAO =====")
    print(f"spam_propaganda: {cont['spam_propaganda']} | "
          f"responde_se: {cont['responde_se']} | "
          f"precisa_humano: {cont['precisa_humano']}")
    print(f"acoes executadas: {cont['acoes']} | erros: {cont['erros']}")
    print(f"modo: {'DRY-RUN (nada foi alterado)' if dry_run else 'PRODUCAO'}")


if __name__ == "__main__":
    run("--dry-run" in sys.argv)
