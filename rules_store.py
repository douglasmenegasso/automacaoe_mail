"""Persistência de regras de remetentes via GitHub Contents API.

As regras (remetentes bloqueados e confiáveis) moram no arquivo rules.json
do repositório. Este módulo lê e grava esse arquivo pela API do GitHub,
para que as regras sobrevivam entre execuções (o /tmp da Vercel é volátil).

Uso:
    from rules_store import load_rules, save_rules
    regras = load_rules()     -> {"blocked_senders": [...], "trusted_senders": [...]}
    save_rules(regras)        -> commita o rules.json atualizado
"""
import base64
import json
import os
import time

import requests

GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "douglasmenegasso/automacaoe_mail")
RULES_PATH = "rules.json"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{RULES_PATH}"

DEFAULT_RULES = {"blocked_senders": [], "trusted_senders": []}


def _headers():
    return {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
    }


def _fetch():
    """Lê o rules.json do GitHub. Retorna (regras, sha).

    Se o arquivo ainda não existir, retorna regras vazias e sha None.
    """
    resp = requests.get(API_URL, headers=_headers(), timeout=30)
    if resp.status_code == 404:
        return dict(DEFAULT_RULES), None
    resp.raise_for_status()
    data = resp.json()
    conteudo = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(conteudo), data["sha"]


def load_rules() -> dict:
    """Retorna as regras atuais. Se algo falhar, retorna vazias (não quebra o bot)."""
    try:
        regras, _sha = _fetch()
        regras.setdefault("blocked_senders", [])
        regras.setdefault("trusted_senders", [])
        return regras
    except Exception as e:
        print(f"[RULES] falha ao ler do GitHub: {e}")
        return dict(DEFAULT_RULES)


def save_rules(rules: dict, max_tentativas: int = 3) -> bool:
    """Commita as regras no rules.json.

    Se outro commit mexer no arquivo ao mesmo tempo (conflito 409),
    relê e tenta de novo, até max_tentativas.
    """
    for tentativa in range(1, max_tentativas + 1):
        try:
            _atual, sha = _fetch()
            payload = {
                "message": "automail: atualiza regras de remetentes",
                "content": base64.b64encode(
                    json.dumps(rules, indent=2, ensure_ascii=False).encode("utf-8")
                ).decode("utf-8"),
            }
            if sha:
                payload["sha"] = sha
            resp = requests.put(API_URL, headers=_headers(), json=payload, timeout=30)
            if resp.status_code in (200, 201):
                print(f"[RULES] regras salvas no GitHub (tentativa {tentativa}).")
                return True
            if resp.status_code == 409:
                print(f"[RULES] conflito na tentativa {tentativa}; relendo e tentando de novo...")
                time.sleep(1)
                continue
            print(f"[RULES] erro ao salvar ({resp.status_code}): {resp.text[:200]}")
            return False
        except Exception as e:
            print(f"[RULES] exceção ao salvar: {e}")
            return False
    print("[RULES] não consegui salvar após as tentativas.")
    return False
