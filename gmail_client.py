"""Autenticação na API do Gmail (OAuth2).

Pré-requisitos:
1. Acesse https://console.cloud.google.com/ e crie um projeto.
2. Ative a "Gmail API".
3. Configure a tela de consentimento OAuth (tipo Externo, adicione seu e-mail como test user).
4. Baixe o JSON de credenciais do tipo "Desktop app" e salve como credentials.json neste diretório.
5. Rode: python gmail_client.py --login  (abrirá o navegador para autorizar; gera token.json)
"""
import base64
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Escopos: leitura, envio, exclusão e modificação de labels (arquivar/marcar lido)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_JSON = os.path.join(BASE_DIR, "credentials.json")
TOKEN_JSON = os.path.join(BASE_DIR, "token.json")


def get_credentials() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_JSON):
        creds = Credentials.from_authorized_user_file(TOKEN_JSON, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_JSON):
                sys.exit(
                    f"[ERRO] {CREDENTIALS_JSON} não encontrado.\n"
                    "Baixe as credenciais OAuth (Desktop app) no Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_JSON, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_JSON, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def build_service():
    return build("gmail", "v1", credentials=get_credentials())


def extract_email_data(msg: dict) -> dict:
    """Extrai campos úteis de uma mensagem da API do Gmail."""
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


if __name__ == "__main__":
    if "--login" in sys.argv:
        get_credentials()
        print("[OK] Autorização concluída. token.json gerado.")
    else:
        print("Uso: python gmail_client.py --login")
