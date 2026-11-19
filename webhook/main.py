"""Webhook do WhatsApp (Fase C+): recebe mensagens e executa comandos.

Roda no Google Cloud Run (gratuito). A Meta chama /webhook quando voce
responde no WhatsApp.
"""
import json
import os
import re

import requests
from flask import Flask, request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)

META_TOKEN = os.environ["META_WA_ACCESS_TOKEN"]
META_PHONE_ID = os.environ["META_WA_PHONE_NUMBER_ID"]
META_API = os.environ.get("META_API_VERSION", "v27.0")
VERIFY_TOKEN = os.environ["WEBHOOK_VERIFY_TOKEN"]
GITHUB_PAT = os.environ["GITHUB_PAT"]
GITHUB_REPO = os.environ.get("GITHUB_REPO", "douglasmenegasso/automacaoe_mail")
GITHUB_WORKFLOW = os.environ.get("GITHUB_WORKFLOW", "automail.yml")
GMAIL_TOKEN_JSON = os.environ["GMAIL_TOKEN"]

LABEL = "AutoMail"
SUBPASTAS = ["Spam", "Atencao", "Seguranca", "Financeiro", "Bancos",
             "Pessoal", "Trabalho", "Outros", "Respostas"]


# ----------------------------- Gmail -----------------------------
def _gmail():
    creds = Credentials.from_authorized_user_info(json.loads(GMAIL_TOKEN_JSON))
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _label_id(service, name, create=False):
    resp = service.users().labels().list(userId="me").execute()
    for lb in resp.get("labels", []):
        if lb["name"].lower() == name.lower():
            return lb["id"]
    if not create:
        return None
    novo = service.users().labels().create(
        userId="me",
        body={"name": name, "labelListVisibility": "labelShow",
              "messageListVisibility": "show"}).execute()
    return novo["id"]


def _latest(service, q):
    resp = service.users().messages().list(userId="me", q=q, maxResults=1).execute()
    ids = resp.get("messages", [])
    return ids[0]["id"] if ids else None


def _modify(service, mid, add=None, remove=None):
    body = {}
    if add:
        body["addLabelIds"] = add
    if remove:
        body["removeLabelIds"] = remove
    service.users().messages().modify(userId="me", id=mid, body=body).execute()


# ----------------------------- WhatsApp -----------------------------
def send_wa(to, text):
    r = requests.post(
        f"https://graph.facebook.com/{META_API}/{META_PHONE_ID}/messages",
        headers={"Authorization": f"Bearer {META_TOKEN}"},
        json={"messaging_product": "whatsapp", "to": to,
              "type": "text", "text": {"body": text}},
    )
    return r.ok


# ----------------------------- Comandos -----------------------------
def _cmd_ajuda():
    return (
        "🤖 *AUTOMAIL — comandos*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "verificar → analisa a caixa AGORA\n"
        "status → resumo das pastas\n"
        "nao e spam <termo> → tira do Spam e devolve p/ entrada\n"
        "mover <termo> para <pasta> → move p/ AutoMail/<pasta>\n"
        "arquivar <termo> → tira da Caixa de Entrada\n"
        "ultimos <n> → lista os n e-mails recentes\n"
        "ajuda → esta lista"
    )


def _cmd_verificar():
    url = (f"https://api.github.com/repos/{GITHUB_REPO}"
           f"/actions/workflows/{GITHUB_WORKFLOW}/dispatches")
    r = requests.post(
        url,
        headers={"Authorization": f"token {GITHUB_PAT}",
                 "Accept": "application/vnd.github+json"},
        json={"ref": "main", "inputs": {"dry_run": "false"}},
    )
    if r.status_code in (200, 204):
        return "🔄 Análise disparada! Rodo agora e te aviso se achar algo importante."
    return f"⚠️ Falha ao disparar ({r.status_code}): {r.text[:120]}"


def _cmd_status():
    s = _gmail()
    linhas = []
    for nome in SUBPASTAS:
        lid = _label_id(s, f"{LABEL}/{nome}")
        if not lid:
            continue
        resp = s.users().messages().list(userId="me", q=f"label:{lid}",
                                         maxResults=500).execute()
        linhas.append(f"• {nome}: {len(resp.get('messages', []))}")
    return "📊 *Status das pastas*\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(linhas)


def _cmd_nao_spam(termo):
    s = _gmail()
    spam_id = _label_id(s, f"{LABEL}/Spam")
    aten_id = _label_id(s, f"{LABEL}/Atencao", create=True)
    q = f"label:{spam_id}"
    if termo:
        q += f" {termo}"
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei nenhum e-mail no Spam com esse termo."
    _modify(s, mid, add=[aten_id, "INBOX"], remove=[spam_id])
    return "✅ Tirado do Spam e devolvido pra Caixa de Entrada (marcado como Atenção)."


def _cmd_mover(termo, pasta):
    s = _gmail()
    pai = _label_id(s, LABEL)
    q = f"label:{pai}"
    if termo:
        q += f" {termo}"
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei e-mail com esse termo."
    alvo = _label_id(s, f"{LABEL}/{pasta}", create=True)
    remove = []
    for nome in SUBPASTAS:
        lid = _label_id(s, f"{LABEL}/{nome}")
        if lid and lid != alvo:
            remove.append(lid)
    _modify(s, mid, add=[alvo], remove=remove)
    return f"✅ Movido para AutoMail/{pasta}."


def _cmd_arquivar(termo):
    s = _gmail()
    pai = _label_id(s, LABEL)
    q = f"label:{pai}"
    if termo:
        q += f" {termo}"
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei e-mail com esse termo."
    _modify(s, mid, remove=["INBOX"])
    return "✅ Arquivado (saiu da Caixa de Entrada, continua nas pastas)."


def _cmd_ultimos(n):
    s = _gmail()
    pai = _label_id(s, LABEL)
    resp = s.users().messages().list(userId="me", q=f"label:{pai}",
                                     maxResults=int(n)).execute()
    linhas = []
    for m in resp.get("messages", []):
        full = s.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject"]).execute()
        hdr = {h["name"]: h["value"]
               for h in full.get("payload", {}).get("headers", [])}
        linhas.append(f"• {hdr.get('From', '?')} — {hdr.get('Subject', '(sem assunto)')[:50]}")
    return f"📥 *Últimos {n}*\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(linhas)


def handle(text):
    t = text.strip().lower()
    if t in ("ajuda", "help", "?"):
        return _cmd_ajuda()
    if t.startswith("verificar"):
        return _cmd_verificar()
    if t.startswith("status"):
        return _cmd_status()
    if t.startswith(("nao e spam", "não é spam", "nao eh spam")):
        termo = re.sub(r"^(nao e spam|não é spam|nao eh spam)\s*", "",
                       text, flags=re.I).strip()
        return _cmd_nao_spam(termo)
    m = re.match(r"mover (.+?) para ([\w\- ]+)", t)
    if m:
        return _cmd_mover(m.group(1).strip(), m.group(2).strip().title().replace(" ", ""))
    if t.startswith("arquivar"):
        return _cmd_arquivar(text[len("arquivar"):].strip())
    m = re.match(r"ultimos (\d+)", t)
    if m:
        return _cmd_ultimos(m.group(1))
    return _cmd_ajuda()


# ----------------------------- Webhook -----------------------------
@app.get("/")
def health():
    return "Automail webhook vivo ✅", 200


@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "forbidden", 403


@app.post("/webhook")
def webhook():
    data = request.get_json(silent=True) or {}
    try:
        entry = data["entry"][0]["changes"][0]["value"]
    except Exception:
        return "ok", 200
    if "messages" not in entry:
        return "ok", 200
    msg = entry["messages"][0]
    wa_id = msg.get("from")
    text = (msg.get("text") or {}).get("body", "").strip()
    if not text:
        return "ok", 200
    reply = handle(text)
    if reply:
        send_wa(wa_id, reply)
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
