"""Exclusão em massa por data, rodada no GitHub Actions (sem limite de 30s)."""
import sys

import settings
from gmail_client import build_service
from whatsapp_notifier import send_whatsapp


def _query(data_str):
    from datetime import datetime
    dt = datetime.strptime(data_str.strip(), "%d/%m/%Y")
    return f"in:inbox before:{dt.strftime('%Y/%m/%d')}"


def run(data_str, modo):
    cfg = settings.load_config()
    service = build_service()
    q = _query(data_str)

    processados = 0
    ja_excluidos = 0
    erros = 0

    # Lista sempre a 1a pagina: conforme apaga, o proximo lote aparece
    while True:
        resp = service.users().messages().list(
            userId="me", q=q, maxResults=500).execute()
        ids = [m["id"] for m in resp.get("messages", [])]
        if not ids:
            break
        for mid in ids:
            try:
                if modo == "trash":
                    service.users().messages().trash(
                        userId="me", id=mid).execute()
                else:
                    service.users().messages().delete(
                        userId="me", id=mid).execute()
                processados += 1
            except Exception as e:
                if "404" in str(e):
                    ja_excluidos += 1  # ja tinha sido excluido: nao e erro
                else:
                    erros += 1

    emoji = "♻️" if modo == "trash" else "💀"
    destino = ("movidos à lixeira" if modo == "trash"
               else "excluídos permanentemente")
    texto = (
        f"{emoji} *Limpeza concluída*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Emails {destino}: {processados}\n"
        f"Já haviam sido excluídos: {ja_excluidos}\n"
        f"Erros: {erros}\n"
        f"Data limite: {data_str}"
    )
    print(texto)
    send_whatsapp(cfg, texto)


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
