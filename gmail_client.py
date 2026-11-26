"""Autenticação na API do Gmail (OAuth2).

Em PRODUÇÃO (GitHub Actions / Vercel):
  Lê o JSON direto da variável de ambiente GMAIL_TOKEN.

LOCAL (desenvolvimento):
  Use: python gmail_client.py --login
  Gera token.json após autorização no navegador.
"""
import json
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# (Escopos mantidos apenas para referência / --login local;
#  em produção o refresh NÃO repassa escopos para evitar invalid_scope.)
SCOPES = [
    "https://mail.google.com/",
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_JSON = os.path.join(BASE_DIR, "token.json")


def _load_token_info() -> dict:
    """Retorna o dict com o JSON do token.

    Prioridade:
      1. Variável de ambiente GMAIL_TOKEN (produção)
      2. Arquivo token.json (desenvolvimento)
    Lança SystemExit se nenhum dos dois existir.
    """
    env_token = os.environ.get("GMAIL_TOKEN", "").strip()
    if env_token:
        try:
            return json.loads(env_token)
        except json.JSONDecodeError as e:
            sys.exit(f"[ERRO] GMAIL_TOKEN não é JSON válido: {e}")

    if os.path.exists(TOKEN_JSON):
        with open(TOKEN_JSON, encoding="utf-8") as f:
            return json.load(f)

    sys.exit(
        "[ERRO] Nenhuma credencial encontrada.\n"
        "• Produção: defina a variável GMAIL_TOKEN.\n"
        "• Local: rode 'python gmail_client.py --login'."
    )


def get_credentials() -> Credentials:
    """Monta a credencial OAuth a partir do token (env ou arquivo).

    - NÃO repassa SCOPES no refresh (evita invalid_scope do Google).
    - Faz refresh automático se o access_token expirou.
    """
    info = _load_token_info()
    # Sem passar SCOPES: usa os escopos que já vieram no token original.
    creds = Credentials.from_authorized_user_info(info)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            sys.exit(
                "[ERRO] Credencial inválida e sem refresh_token.\n"
                "Gere um novo token e atualize GMAIL_TOKEN."
            )

    return creds


def build_service():
    return build("gmail", "v1", credentials=get_credentials())


def extract_email_data(msg: dict) -> dict:
    """Extrai campos úteis de uma mensagem da API do Gmail."""
    import base64

    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}

    body_parts = []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if mime == "text/plain":
                body_parts.insert(0, text)
            elif mime == "text/html":
                body_parts.append(text)
        for p in part.get("parts", []) or []:
            walk(p)

    walk(msg.get("payload", {}))
    body = "\n".join(body_parts) if body_parts else ""

    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        "label_ids": msg.get("labelIds", []),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(sem assunto)"),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "body": body[:4000],  # limita tamanho para o modelo
    }


def _do_local_login():
    """Fluxo de login local (navegador). Salva token.json."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials_json = os.path.join(BASE_DIR, "credentials.json")
    if not os.path.exists(credentials_json):
        sys.exit(
            f"[ERRO] {credentials_json} não encontrado.\n"
            "Baixe as credenciais OAuth (Desktop app) no Google Cloud Console."
        )

    flow = InstalledAppFlow.from_client_secrets_file(credentials_json, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_JSON, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print("[OK] Autorização concluída. token.json gerado.")


if __name__ == "__main__":
    if "--login" in sys.argv:
        _do_local_login()
    else:
        print("Uso: python gmail_client.py --login")
