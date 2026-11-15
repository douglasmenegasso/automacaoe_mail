"""Envio de notificações por WhatsApp.

Suporta três provedores (escolha em config.json -> whatsapp.provider):
- "twilio": use uma conta Twilio com WhatsApp habilitado (https://www.twilio.com/whatsapp)
- "infobip": use a API REST da Infobip (WhatsApp)
- "meta": WhatsApp Cloud API oficial da Meta (grátis até 1.000 conversas/dia)
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
    if provider == "meta":
        return _send_meta(wa_cfg["meta"], message)
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


def _send_meta(cfg: dict, message: str) -> bool:
    """WhatsApp Cloud API oficial da Meta.

    Requisitos:
    - Conta no Meta for Developers com um app "WhatsApp" criado
      (https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)
    - PHONE_NUMBER_ID e ACCESS_TOKEN (temporário de 24h ou permanente via
      System User) em variáveis de ambiente.
    - O número de destino precisa ter enviado mensagem ao número do bot nas
      últimas 24h (janela de sessão), OU usar templates aprovados.
    """
    token = os.environ.get(cfg.get("access_token_env", "META_WA_ACCESS_TOKEN"), "")
    phone_id = os.environ.get(cfg.get("phone_number_id_env", "META_WA_PHONE_NUMBER_ID"), "")
    to_number = cfg.get("to_number", "")
    if not token or not phone_id or not to_number:
        print("[ERRO WhatsApp/Meta] Faltam META_WA_ACCESS_TOKEN, META_WA_PHONE_NUMBER_ID ou to_number.")
        return False
    version = cfg.get("api_version", "v21.0")
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number.replace("whatsapp:", "").replace("+", ""),
        "type": "text",
        "text": {"preview_url": False, "body": message},
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=30,
    )
    ok = resp.status_code == 200
    print(f"[WhatsApp/Meta] {'OK' if ok else 'FALHA'} ({resp.status_code}) {resp.text[:200]}")
    return ok
