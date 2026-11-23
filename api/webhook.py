"""Webhook do WhatsApp (Fase C+): recebe mensagens, interpreta comandos E cliques de botões."""
import json
import os
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

META_TOKEN = os.environ.get("META_WA_ACCESS_TOKEN", "")
META_PHONE_ID = os.environ.get("META_WA_PHONE_NUMBER_ID", "")
META_API = os.environ.get("META_API_VERSION", "v27.0")
VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "")
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "douglasmenegasso/automacaoe_mail")
GITHUB_WORKFLOW = os.environ.get("GITHUB_WORKFLOW", "automail.yml")
GMAIL_TOKEN_JSON = os.environ.get("GMAIL_TOKEN", "{}")

LABEL = "AutoMail"
SUBPASTAS = ["Spam", "Atencao", "Seguranca", "Financeiro", "Bancos",
             "Pessoal", "Trabalho", "Outros", "Respostas"]
RULES_FILE_LOCAL = "/tmp/rules.json"  # Caminho temporário no Vercel


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


def send_wa(to, text, buttons=None):
    """Envia mensagem com botões opcionais."""
    print(f"📤 Tentando enviar para {to}: {text[:30]}...")
    
    if buttons:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}}
                        for b in buttons[:3]
                    ]
                }
            }
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text}
        }
    
    r = requests.post(
        f"https://graph.facebook.com/{META_API}/{META_PHONE_ID}/messages",
        headers={"Authorization": f"Bearer {META_TOKEN}"},
        json=payload,
    )
    print(f"📥 Resposta do envio: {r.status_code} - {r.text}")
    return r.ok


def _cmd_ajuda():
    """Ajuda reformulada com botões."""
    texto = (
        "🤖 *AUTOMAIL — menu principal*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Escolha uma opção abaixo ou digite o comando.\n\n"
        "*Comandos disponíveis:*\n"
        "• verificar → analisa a caixa AGORA\n"
        "• status → resumo das pastas\n"
        "• nao e spam <termo> → tira do Spam\n"
        "• mover <termo> para <pasta> → move\n"
        "• arquivar <termo> → tira da entrada\n"
        "• ultimos <n> → lista os n recentes\n"
        "• limpar <dd/mm/aaaa> → apaga emails ANTES dessa data\n"
        "• lixeira → mostra/apaga/recupera da lixeira\n"
        "• ajuda → esta lista"
    )
    buttons = [
        {"id": "cmd_verificar", "title": "🔄 Verificar Agora"},
        {"id": "cmd_status", "title": "📊 Status Pastas"},
        {"id": "cmd_lixeira", "title": "🗑️ Abrir Lixeira"},
    ]
    return texto, buttons


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
        return "🔄 Análise disparada! Vou analisar agora e te aviso se achar algo importante."
    return f"⚠️ Falha ao disparar ({r.status_code})"


def _cmd_status():
    s = _gmail()
    linhas = []
    total = 0
    for nome in SUBPASTAS:
        lid = _label_id(s, f"{LABEL}/{nome}")
        if not lid:
            continue
        resp = s.users().messages().list(userId="me", q=f"label:{lid}",
                                         maxResults=500).execute()
        count = len(resp.get("messages", []))
        linhas.append(f"• {nome}: {count}")
        total += count
    header = f"📊 *Status* (total: {total})\n━━━━━━━━━━━━━━━━━━\n"
    return header + "\n".join(linhas)


def _cmd_nao_spam(termo):
    s = _gmail()
    spam_id = _label_id(s, f"{LABEL}/Spam")
    aten_id = _label_id(s, f"{LABEL}/Atencao", create=True)
    q = f"label:{spam_id}"
    if termo:
        q += f" {termo}"
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei no Spam com esse termo."
    _modify(s, mid, add=[aten_id, "INBOX"], remove=[spam_id])
    return "✅ Tirado do Spam, devolvido pra entrada."


def _cmd_mover(termo, pasta):
    s = _gmail()
    pai = _label_id(s, LABEL)
    q = f"label:{pai}"
    if termo:
        q += f" {termo}"
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei com esse termo."
    alvo = _label_id(s, f"{LABEL}/{pasta}", create=True)
    remove = []
    for nome in SUBPASTAS:
        lid = _label_id(s, f"{LABEL}/{nome}")
        if lid and lid != alvo:
            remove.append(lid)
    _modify(s, mid, add=[alvo], remove=remove)
    return f"✅ Movido para {LABEL}/{pasta}."


def _cmd_arquivar(termo):
    s = _gmail()
    pai = _label_id(s, LABEL)
    q = f"label:{pai}"
    if termo:
        q += f" {termo}"
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei com esse termo."
    _modify(s, mid, remove=["INBOX"])
    return "✅ Arquivado."


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
        linhas.append(f"• {hdr.get('From', '?')[:30]} — {hdr.get('Subject', '?')[:40]}")
    return f"📥 *Últimos {n}*\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(linhas)


def _cmd_limpar(data_str):
    """Apaga todos os emails ANTES da data informada (dd/mm/aaaa)."""
    try:
        from datetime import datetime
        dt_limit = datetime.strptime(data_str.strip(), "%d/%m/%Y")
    except ValueError:
        return "❌ Data inválida. Use dd/mm/aaaa. Ex: limpar 01/01/2024"
    
    s = _gmail()
    # Query: emails recebidos antes da data limite
    query_date = dt_limit.strftime("%Y/%m/%d")
    q = f"before:{query_date}"
    
    resp = s.users().messages().list(userId="me", q=q, maxResults=500).execute()
    ids = resp.get("messages", [])
    
    if not ids:
        return f"🤷 Nenhum email encontrado antes de {data_str}."
    
    apagados = 0
    errors = 0
    for item in ids:
        try:
            s.users().messages().delete(userId="me", id=item["id"]).execute()
            apagados += 1
        except Exception as e:
            errors += 1
    
    result = f"🗑️ *Limpeza concluída*\n━━━━━━━━━━━━━━━━━━\nEmails apagados: {apagados}\nErros: {errors}\nData limite: {data_str}"
    return result


def _cmd_lixeira(action="", termo=""):
    """Gerencia a lixeira do Gmail.
    action: vazio=listar, recuperar=<id>, apagar=<id>, esvaziar=tudo
    """
    s = _gmail()
    
    if action == "esvaziar":
        # Apaga permanentemente TUDO na lixeira
        resp = s.users().messages().list(userId="me", q="in:trash", maxResults=500).execute()
        ids = resp.get("messages", [])
        if not ids:
            return "🗑️ Lixeira já está vazia!"
        
        apagados = 0
        for item in ids:
            try:
                s.users().messages().delete(userId="me", id=item["id"]).execute()
                apagados += 1
            except Exception:
                pass
        
        return f"🗑️ Lixeira esvaziada! {apagados} emails apagados permanentemente."
    
    if action.startswith("recuperar::"):
        msg_id = action.split("::")[1]
        try:
            _modify(s, msg_id, add=["INBOX"], remove=["TRASH"])
            return f"✅ Email recuperado da lixeira e devolvido à entrada."
        except Exception as e:
            return f"❌ Erro ao recuperar: {str(e)[:50]}"
    
    if action.startswith("apagar::"):
        msg_id = action.split("::")[1]
        try:
            s.users().messages().delete(userId="me", id=msg_id).execute()
            return f"✅ Email apagado PERMANENTEMENTE da lixeira."
        except Exception as e:
            return f"❌ Erro ao apagar: {str(e)[:50]}"
    
    # Listar lixeira (padrão)
    q = "in:trash"
    if termo:
        q += f" {termo}"
    
    resp = s.users().messages().list(userId="me", q=q, maxResults=20).execute()
    items = resp.get("messages", [])
    
    if not items:
        return "🗑️ Lixeira vazia (ou sem resultados pro termo)."
    
    linhas = []
    buttons = []
    for i, m in enumerate(items[:10]):  # Máx 10 pra caber nos botões
        full = s.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]).execute()
        hdr = {h["name"]: h["value"]
               for h in full.get("payload", {}).get("headers", [])}
        assunto = hdr.get("Subject", "?")[:30]
        remetente = hdr.get("From", "?")[:25]
        data = hdr.get("Date", "?")[:10]
        linhas.append(f"{i+1}. {remetente} — {assunto} ({data})")
        
        # Botões de ação para cada email
        buttons.append({"id": f"lixeira_recuperar::{m['id']}", "title": f"♻️ Recuperar {i+1}"})
        buttons.append({"id": f"lixeira_apagar::{m['id']}", "title": f"❌ Apagar {i+1}"})
    
    texto = "🗑️ *LIXEIRA*\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(linhas) + "\n\nUse os botões abaixo:"
    
    # Meta só aceita 3 botões por mensagem, então mando só os primeiros 3
    final_buttons = buttons[:3] if buttons else None
    
    return texto, final_buttons


def handle_button_click(button_id: str, wa_id: str) -> tuple[str, list] | None:
    """Interpreta clique em botão e retorna resposta (+ botões extras se necessário)."""
    
    # Formato: tipo::valor
    parts = button_id.split("::")
    tipo = parts[0]
    valor = "::".join(parts[1:]) if len(parts) > 1 else ""
    
    if tipo == "cmd_verificar":
        return _cmd_verificar(), None
    
    if tipo == "cmd_status":
        return _cmd_status(), None
    
    if tipo == "cmd_lixeira":
        result = _cmd_lixeira()
        if isinstance(result, tuple):
            return result
        return result, None
    
    if tipo == "seguro":
        # Marca remetente como confiável (nunca spam)
        sender = valor
        rules = _load_rules_local()
        if sender not in rules.get("trusted_senders", []):
            rules.setdefault("trusted_senders", []).append(sender)
            _save_rules_local(rules)
        return f"✅ Remetente {sender} marcado como CONFIÁVEL. Futuros emails dele nunca serão spam.", None
    
    if tipo == "spam_remetente":
        # Pergunta confirmação antes de aplicar regra
        sender = valor
        confirm_text = (
            f"🚫 Confirmar: bloquear TODOS os futuros emails de:\n*{sender}*?\n\n"
            "Isso cria uma regra permanente e economiza créditos de IA."
        )
        confirm_buttons = [
            {"id": f"confirmar_spam::{sender}", "title": "✅ Sim, Bloquear"},
            {"id": f"cancelar_spam::{sender}", "title": "❌ Cancelar"},
        ]
        return confirm_text, confirm_buttons
    
    if tipo == "confirmar_spam":
        sender = valor
        rules = _load_rules_local()
        if sender not in rules.get("blocked_senders", []):
            rules.setdefault("blocked_senders", []).append(sender)
            _save_rules_local(rules)
        return f"🚫 Remetente {sender} BLOQUEADO. Todos os emails futuros dele irão direto pro Spam sem análise de IA.", None
    
    if tipo == "cancelar_spam":
        return "ℹ️ Ação cancelada. Nenhuma regra foi criada.", None
    
    if tipo == "mover_pasta":
        # Pede qual pasta mover
        msg_id = valor
        mover_text = "📁 Para qual pasta deseja mover este email?"
        mover_buttons = [
            {"id": f"exec_move::{msg_id}::Seguranca", "title": "🔒 Seguranca"},
            {"id": f"exec_move::{msg_id}::Financeiro", "title": "💰 Financeiro"},
            {"id": f"exec_move::{msg_id}::Bancos", "title": "🏦 Bancos"},
        ]
        return mover_text, mover_buttons
    
    if tipo == "exec_move":
        # Formato: msg_id::pasta
        subparts = valor.split("::")
        msg_id = subparts[0]
        pasta = subparts[1] if len(subparts) > 1 else "Atencao"
        s = _gmail()
        pai = _label_id(s, LABEL)
        alvo = _label_id(s, f"{LABEL}/{pasta}", create=True)
        remove = []
        for nome in SUBPASTAS:
            lid = _label_id(s, f"{LABEL}/{nome}")
            if lid and lid != alvo:
                remove.append(lid)
        _modify(s, msg_id, add=[alvo], remove=remove)
        return f"✅ Email movido para {LABEL}/{pasta}.", None
    
    if tipo.startswith("lixeira_recuperar"):
        msg_id = valor
        result = _cmd_lixeira(f"recuperar::{msg_id}")
        return result, None
    
    if tipo.startswith("lixeira_apagar"):
        msg_id = valor
        result = _cmd_lixeira(f"apagar::{msg_id}")
        return result, None
    
    return None


def _load_rules_local() -> dict:
    """Carrega rules.json localmente (no container efêmero do Vercel)."""
    try:
        with open(RULES_FILE_LOCAL, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"blocked_senders": [], "trusted_senders": []}


def _save_rules_local(rules: dict):
    """Salva rules.json localmente. NOTA: no Vercel isso é VOLÁTIL (container morre).
    Para persistência real, precisaria commitar no GitHub ou usar storage externo."""
    with open(RULES_FILE_LOCAL, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)


class handler(BaseHTTPRequestHandler):
    def _resp(self, code, body=""):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body.encode() if isinstance(body, str) else body)

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        mode = qs.get("hub.mode", [""])[0]
        token = qs.get("hub.verify_token", [""])[0]
        challenge = qs.get("hub.challenge", [""])[0]
        if mode == "subscribe" and token == VERIFY_TOKEN:
            self._resp(200, challenge)
        else:
            self._resp(403, "forbidden")

    def do_POST(self):
        print("🔔 POST recebido!")
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            print("📦 Dados recebidos:", json.dumps(data))
        except Exception as e:
            print("❌ Erro ao ler body:", e)
            self._resp(200, "ok")
            return
        
        try:
            entry = data["entry"][0]["changes"][0]["value"]
            print("📝 Entry:", json.dumps(entry))
        except Exception as e:
            print("❌ Erro ao extrair entry:", e)
            self._resp(200, "ok")
            return
            
        if "messages" not in entry:
            print("⚠️ Sem 'messages' no entry")
            self._resp(200, "ok")
            return
            
        msg = entry["messages"][0]
        wa_id = msg.get("from")
        msg_type = msg.get("type", "text")
        
        # Caso 1: Clique em botão (mensagem interativa)
        if msg_type == "interactive":
            interactive = msg.get("interactive", {})
            button_reply = interactive.get("button_reply", {})
            list_reply = interactive.get("list_reply", {})
            
            button_id = button_reply.get("id") or list_reply.get("id") or ""
            print(f"👆 Botão clicado: {button_id}")
            
            result = handle_button_click(button_id, wa_id)
            if result:
                reply_text, reply_buttons = result
                if reply_text:
                    success = send_wa(wa_id, reply_text, buttons=reply_buttons)
                    print(f"✅ Envio realizado? {success}")
            
            self._resp(200, "ok")
            return
        
        # Caso 2: Texto normal
        text = (msg.get("text") or {}).get("body", "").strip()
        print(f"👤 wa_id: {wa_id} | 💬 text: '{text}'")
        
        if not text:
            print("⚠️ Texto vazio, ignorando")
            self._resp(200, "ok")
            return
        
        t = text.strip().lower()
        reply_text = None
        reply_buttons = None
        
        if t in ("ajuda", "help", "?"):
            reply_text, reply_buttons = _cmd_ajuda()
        elif t.startswith("verificar"):
            reply_text = _cmd_verificar()
        elif t.startswith("status"):
            reply_text = _cmd_status()
        elif t.startswith(("nao e spam", "não é spam", "nao eh spam")):
            termo = re.sub(r"^(nao e spam|não é spam|nao eh spam)\s*", "",
                           text, flags=re.I).strip()
            reply_text = _cmd_nao_spam(termo)
        elif re.match(r"^mover (.+?) para ([\w\- ]+)$", t):
            m = re.match(r"mover (.+?) para ([\w\- ]+)", t)
            reply_text = _cmd_mover(m.group(1).strip(), m.group(2).strip().title().replace(" ", ""))
        elif t.startswith("arquivar"):
            reply_text = _cmd_arquivar(text[len("arquivar"):].strip())
        elif re.match(r"^ultimos (\d+)$", t):
            m = re.match(r"ultimos (\d+)", t)
            reply_text = _cmd_ultimos(m.group(1))
        elif t.startswith("limpar"):
            data_arg = text[len("limpar"):].strip()
            reply_text = _cmd_limpar(data_arg)
        elif t.startswith("lixeira"):
            resto = text[len("lixeira"):].strip()
            if resto.startswith("esvaziar"):
                reply_text = _cmd_lixeira("esvaziar")
            elif resto:
                result = _cmd_lixeira("", resto)
                if isinstance(result, tuple):
                    reply_text, reply_buttons = result
                else:
                    reply_text = result
            else:
                result = _cmd_lixeira()
                if isinstance(result, tuple):
                    reply_text, reply_buttons = result
                else:
                    reply_text = result
        else:
            reply_text, reply_buttons = _cmd_ajuda()
        
        print(f"🤖 Reply gerado: {(reply_text or '')[:50]}...")
        
        if reply_text:
            success = send_wa(wa_id, reply_text, buttons=reply_buttons)
            print(f"✅ Envio realizado? {success}")
            
        self._resp(200, "ok")
