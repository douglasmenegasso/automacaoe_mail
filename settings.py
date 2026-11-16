"""Carrega o config.json do projeto com valores padrão garantidos."""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULTS = {
    "gmail": {
        "credentials_json": "credentials.json",
        "token_json": "token.json",
        "max_emails_per_run": 50,
        "query": "in:inbox",
    },
    "ai": {"timeout_seconds": 30, "providers": []},
    "whatsapp": {"provider": "console"},
    "automation": {
        "auto_delete_spam": False,
        "auto_reply_enabled": False,
        "notify_email": "",
        "language": "portuguese",
    },
}


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise SystemExit(
            "[ERRO] config.json nao encontrado. "
            "Copie config.example.json para config.json e ajuste."
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    for secao, padroes in DEFAULTS.items():
        bloco = cfg.setdefault(secao, {})
        for chave, valor in padroes.items():
            bloco.setdefault(chave, valor)
    return cfg
