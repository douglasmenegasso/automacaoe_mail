"""Envio de notificações por WhatsApp.

Suporta dois provedores (escolha em config.json -> whatsapp.provider):
- "twilio": use uma conta Twilio com WhatsApp habilitado (https://www.twilio.com/whatsapp)
- "infobip": use a API REST da Infobip (WhatsApp)
- "console": apenas imprime no terminal (útil para testes)

As chaves são lidas de variáveis de ambiente (nomes configuráveis no config.json).
"""
import json
import os

import requests


def send_whatsapp(config: dict, message: str) -> bool:
    wa_cfg = config.get("whatsapp", {})
    provider = wa_cfg.get("provider", "console")

    if provider == "twilio":
        return _send_twilio(wa_cfg["twilio"], message)
    if provider == "infobip":
        return _send_infobip(wa_cfg["infobip"], message)
    print(f"[WHATSAPP-console] {message}")
    return True


def _send_twilio(cfg: dict, message: str) -> bool:
    sid = os.environ.get(cfg["account_sid_env"], "")
    token = os.environ.get(cfg["auth_token_env"], "")
    if not sid or not token:
        print("[ERRO WhatsApp] Variáveis de ambiente da Twilio ausentes.")
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    resp = requests.post(
        url,
        auth=(sid, token),
        data={
            "From": cfg["from_number"],
            "To": cfg["to_number"],
            "Body": message,
        },
        timeout=30,
    )
    ok = resp.status_code in (200, 201)
    print(f"[WhatsApp/Twilio] {'OK' if ok else 'FALHA'} ({resp.status_code})")
    return ok


def _send_infobip(cfg: dict, message: str) -> bool:
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        print("[ERRO WhatsApp] Variável de ambiente da Infobip ausente.")
        return False
    url = f"{cfg['base_url'].rstrip('/')}/wa/2/text/send"
    payload = {
        "from": cfg["from_number"],
        "to": cfg["to_number"],
        "text": message,
    }
    resp = requests.post(
        url,
        headers={
            "Authorization": f"App {api_key}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=30,
    )
    ok = resp.status_code in (200, 202)
    print(f"[WhatsApp/Infobip] {'OK' if ok else 'FALHA'} ({resp.status_code}) {resp.text[:200]}")
    return ok
