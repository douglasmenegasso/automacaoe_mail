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
RULES_FILE_LOCAL = "/tmp/rules.json"


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


def send_wa(to, text, buttons=None, list_items=None, header="", footer=""):
    """Envia mensagem com botões OU lista interativa.
    
    Args:
        to: número destino
        text: corpo da mensagem
        buttons: lista [{"id": "...", "title": "..."}] (máx 3, título máx 20 chars)
        list_items: lista [{"id": "...", "title": "...", "description": "..."}] (máx 10, título máx 24 chars)
        header: cabeçalho opcional (para listas)
        footer: rodapé opcional
    """
    print(f"📤 Tentando enviar para {to}: {text[:30]}...")
    
    payload = {"messaging_product": "whatsapp", "to": to}
    
    if list_items and len(list_items) > 0:
        # Mensagem tipo LISTA (rolável, até 10 itens)
        rows = []
        for item in list_items[:10]:
            row = {
                "id": item["id"],
                "title": item["title"][:24],  # Meta limita a 24 chars
            }
            if item.get("description"):
                row["description"] = item["description"][:72]
            rows.append(row)
        
        payload.update({
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {"type": "text", "text": header or "Menu"},
                "body": {"text": text},
                "action": {
                    "button": footer or "Escolha uma opção",
                    "sections": [
                        {"rows": rows}
                    ]
                }
            }
        })
    elif buttons and len(buttons) > 0:
        # Mensagem com BOTÕES (até 3)
        payload.update({
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
        })
    else:
        # Texto simples
        payload.update({
            "type": "text",
            "text": {"body": text}
        })
    
    r = requests.post(
        f"https://graph.facebook.com/{META_API}/{META_PHONE_ID}/messages",
        headers={"Authorization": f"Bearer {META_TOKEN}"},
        json=payload,
    )
    print(f"📥 Resposta do envio: {r.status_code} - {r.text}")
    return r.ok


def _cmd_ajuda():
    """Ajuda LIMPA: só botões principais, sem lista de texto feia."""
    texto = "🤖 *AUTOMAIL*\nComo posso ajudar?"
    buttons = [
        {"id": "menu_acoes", "title": "⚡ Ações rápidas"},
        {"id": "menu_lixeira", "title": "🗑️ Lixeira"},
        {"id": "menu_comandos", "title": "📋 Todos comandos"},
    ]
    return texto, buttons, None


def _cmd_menu_acoes():
    """Menu de ações rápidas."""
    texto = "⚡ *AÇÕES RÁPIDAS*"
    buttons = [
        {"id": "cmd_verificar", "title": "🔄 Analisar agora"},
        {"id": "cmd_status", "title": "📊 Ver status"},
        {"id": "cmd_ultimos::5", "title": "📥 Últimos 5"},
    ]
    return texto, buttons, None


def _cmd_menu_comandos():
    """Lista completa de comandos (quando clicar em 'Todos comandos')."""
    texto = (
        "📋 *COMANDOS DISPONÍVEIS*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "✍️ Digite:\n"
        "• verificar\n"
        "• status\n"
        "• nao e spam <termo>\n"
        "• mover <termo> para <pasta>\n"
        "• arquivar <termo>\n"
        "• ultimos <n>\n"
        "• limpar <dd/mm/aaaa>\n"
        "• lixeira\n\n"
        "Ou use os menus acima."
    )
    return texto, None, None


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
        return "🔄 Análise disparada! Te aviso se achar algo importante.", None, None
    return f"⚠️ Falha ao disparar ({r.status_code})", None, None


def _descobrir_pastas(service):
    """Lê as etiquetas do Gmail e retorna só as que são sub-pastas de AutoMail."""
    resp = service.users().labels().list(userId="me").execute()
    id2name = {lb["id"]: lb["name"] for lb in resp.get("labels", [])}
    
    # Pega o ID da etiqueta pai "AutoMail"
    pai_id = None
    for lid, nome in id2name.items():
        if nome.lower() == LABEL.lower():
            pai_id = lid
            break
    
    if not pai_id:
        return []
    
    # Filtra só as sub-etiquetas (começam com "AutoMail/")
    pastas_encontradas = []
    for lid, nome in id2name.items():
        if nome.startswith(f"{LABEL}/"):
            pasta_nome = nome.split("/", 1)[1]  # Remove "AutoMail/"
            pastas_encontradas.append((pasta_nome, lid))
    
    return sorted(pastas_encontradas)


def _cmd_status():
    s = _gmail()
    pastas = _descobrir_pastas(s)
    
    if not pastas:
        return "📊 *Status*\n━━━━━━━━━━━━━━━━━━\nNenhuma pasta encontrada.", None, None
    
    linhas = []
    total = 0
    for nome_pasta, label_id in pastas:
        # Conta os emails nessa pasta específica
        resp = s.users().messages().list(
            userId="me", 
            q=f"label:{label_id}",
            maxResults=500
        ).execute()
        count = len(resp.get("messages", []))
        linhas.append(f"• {nome_pasta}: {count}")
        total += count
    
    texto = f"📊 *Status* (total: {total})\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(linhas)
    return texto, None, None


def _cmd_nao_spam(termo):
    s = _gmail()
    spam_id = _label_id(s, f"{LABEL}/Spam")
    aten_id = _label_id(s, f"{LABEL}/Atencao", create=True)
    q = f"label:{spam_id}"
    if termo:
        q += f" {termo}"
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei no Spam com esse termo.", None, None
    _modify(s, mid, add=[aten_id, "INBOX"], remove=[spam_id])
    return "✅ Tirado do Spam, devolvido pra entrada.", None, None


def _cmd_mover(termo, pasta):
    s = _gmail()
    pai = _label_id(s, LABEL)
    q = f"label:{pai}"
    if termo:
        q += f" {termo}"
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei com esse termo.", None, None
    alvo = _label_id(s, f"{LABEL}/{pasta}", create=True)
    remove = []
    for nome in SUBPASTAS:
        lid = _label_id(s, f"{LABEL}/{nome}")
        if lid and lid != alvo:
            remove.append(lid)
    _modify(s, mid, add=[alvo], remove=remove)
    return f"✅ Movido para {LABEL}/{pasta}.", None, None


def _cmd_arquivar(termo):
    s = _gmail()
    pai = _label_id(s, LABEL)
    q = f"label:{pai}"
    if termo:
        q += f" {termo}"
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei com esse termo.", None, None
    _modify(s, mid, remove=["INBOX"])
    return "✅ Arquivado.", None, None


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
    texto = f"📥 *Últimos {n}*\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(linhas)
    return texto, None, None


def _cmd_limpar(data_str):
    """Apaga todos os emails ANTES da data informada (dd/mm/aaaa)."""
    try:
        from datetime import datetime
        dt_limit = datetime.strptime(data_str.strip(), "%d/%m/%Y")
    except ValueError:
        return "❌ Data inválida. Use dd/mm/aaaa. Ex: limpar 01/01/2024", None, None
    
    s = _gmail()
    query_date = dt_limit.strftime("%Y/%m/%d")
    q = f"before:{query_date}"
    
    resp = s.users().messages().list(userId="me", q=q, maxResults=500).execute()
    ids = resp.get("messages", [])
    
    if not ids:
        return f"🤷 Nenhum email encontrado antes de {data_str}.", None, None
    
    # Pergunta confirmação antes de apagar
    confirm_texto = (
        f"⚠️ *ATENÇÃO*\n"
        f"Vou apagar PERMANENTEMENTE {len(ids)} emails anteriores a {data_str}.\n\n"
        f"Essa ação NÃO pode ser desfeita."
    )
    confirm_buttons = [
        {"id": f"confirmar_limpar::{data_str}", "title": "✅ Confirmar apagar"},
        {"id": "cancelar", "title": "❌ Cancelar"},
    ]
    return confirm_texto, confirm_buttons, None


def _executar_limpar(data_str):
    """Executa a limpeza após confirmação."""
    from datetime import datetime
    dt_limit = datetime.strptime(data_str.strip(), "%d/%m/%Y")
    s = _gmail()
    query_date = dt_limit.strftime("%Y/%m/%d")
    q = f"before:{query_date}"
    
    resp = s.users().messages().list(userId="me", q=q, maxResults=500).execute()
    ids = resp.get("messages", [])
    
    apagados = 0
    errors = 0
    for item in ids:
        try:
            s.users().messages().delete(userId="me", id=item["id"]).execute()
            apagados += 1
        except Exception:
            errors += 1
    
    texto = f"🗑️ *Limpeza concluída*\n━━━━━━━━━━━━━━━━━━\nEmails apagados: {apagados}\nErros: {errors}\nData limite: {data_str}"
    return texto, None, None


def _cmd_lixeira(termo=""):
    """Mostra a lixeira com lista interativa de recuperação/apagamento."""
    s = _gmail()
    q = "in:trash"
    if termo:
        q += f" {termo}"
    
    resp = s.users().messages().list(userId="me", q=q, maxResults=20).execute()
    items = resp.get("messages", [])
    
    if not items:
        return "🗑️ Lixeira vazia (ou sem resultados pro termo).", None, None
    
    # Monta a lista interativa (até 10 itens)
    list_rows = []
    for i, m in enumerate(items[:10]):
        full = s.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]).execute()
        hdr = {h["name"]: h["value"]
               for h in full.get("payload", {}).get("headers", [])}
        assunto = hdr.get("Subject", "?")[:24]
        remetente = hdr.get("From", "?")[:20]
        list_rows.append({
            "id": f"lixeira_item::{m['id']}",
            "title": f"{i+1}. {assunto}",
            "description": remetente,
        })
    
    texto = "🗑️ Escolha um email da lixeira:"
    return texto, None, list_rows


def _cmd_lixeira_item(msg_id):
    """Depois de escolher um email da lixeira, mostra ações (recuperar/apagar)."""
    s = _gmail()
    full = s.users().messages().get(
        userId="me", id=msg_id, format="metadata",
        metadataHeaders=["From", "Subject", "Date"]).execute()
    hdr = {h["name"]: h["value"]
           for h in full.get("payload", {}).get("headers", [])}
    
    texto = (
        f"🗑️ *Item selecionado*\n"
        f"*De:* {hdr.get('From', '?')}\n"
        f"*Assunto:* {hdr.get('Subject', '?')[:60]}"
    )
    buttons = [
        {"id": f"lixeira_recuperar::{msg_id}", "title": "♻️ Recuperar"},
        {"id": f"lixeira_apagar::{msg_id}", "title": "❌ Apagar def."},
        {"id": "cmd_lixeira", "title": "↩️ Voltar"},
    ]
    return texto, buttons, None


def _cmd_lixeira_esvaziar():
    """Confirmação antes de esvaziar toda a lixeira."""
    s = _gmail()
    resp = s.users().messages().list(userId="me", q="in:trash", maxResults=500).execute()
    ids = resp.get("messages", [])
    
    if not ids:
        return "🗑️ Lixeira já está vazia!", None, None
    
    texto = f"⚠️ Vou apagar PERMANENTEMENTE {len(ids)} emails da lixeira. Confirma?"
    buttons = [
        {"id": "confirmar_esvaziar", "title": "✅ Sim, apagar tudo"},
        {"id": "cancelar", "title": "❌ Cancelar"},
    ]
    return texto, buttons, None


def _executar_esvaziar():
    s = _gmail()
    resp = s.users().messages().list(userId="me", q="in:trash", maxResults=500).execute()
    ids = resp.get("messages", [])
    
    apagados = 0
    for item in ids:
        try:
            s.users().messages().delete(userId="me", id=item["id"]).execute()
            apagados += 1
        except Exception:
            pass
    
    return f"🗑️ Lixeira esvaziada! {apagados} emails apagados permanentemente.", None, None


def _load_rules_local() -> dict:
    try:
        with open(RULES_FILE_LOCAL, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"blocked_senders": [], "trusted_senders": []}


def _save_rules_local(rules: dict):
    with open(RULES_FILE_LOCAL, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)


def handle_button_click(button_id: str, wa_id: str):
    """Interpreta clique em botão ou item de lista. Retorna (texto, buttons, list_items)."""
    
    parts = button_id.split("::")
    tipo = parts[0]
    valor = "::".join(parts[1:]) if len(parts) > 1 else ""
    
    # Menus principais
    if tipo == "menu_acoes":
        return _cmd_menu_acoes()
    if tipo == "menu_lixeira":
        return _cmd_lixeira()
    if tipo == "menu_comandos":
        return _cmd_menu_comandos()
    if tipo == "cancelar":
        return "ℹ️ Ação cancelada.", None, None
    
    # Comandos diretos
    if tipo == "cmd_verificar":
        return _cmd_verificar()
    if tipo == "cmd_status":
        return _cmd_status()
    if tipo.startswith("cmd_ultimos"):
        n = valor or "5"
        return _cmd_ultimos(n)
    if tipo == "cmd_lixeira":
        return _cmd_lixeira()
    
    # Limpeza por data
    if tipo == "confirmar_limpar":
        return _executar_limpar(valor)
    
    # Lixeira
    if tipo.startswith("lixeira_item"):
        return _cmd_lixeira_item(valor)
    if tipo.startswith("lixeira_recuperar"):
        msg_id = valor
        s = _gmail()
        try:
            _modify(s, msg_id, add=["INBOX"], remove=["TRASH"])
            return "✅ Email recuperado da lixeira!", None, None
        except Exception as e:
            return f"❌ Erro: {str(e)[:50]}", None, None
    if tipo.startswith("lixeira_apagar"):
        msg_id = valor
        s = _gmail()
        try:
            s.users().messages().delete(userId="me", id=msg_id).execute()
            return "✅ Email apagado PERMANENTEMENTE.", None, None
        except Exception as e:
            return f"❌ Erro: {str(e)[:50]}", None, None
    if tipo == "confirmar_esvaziar":
        return _executar_esvaziar()
    if tipo == "cmd_esvaziar":
        return _cmd_lixeira_esvaziar()
    
    # Regras de remetentes
    if tipo == "seguro":
        sender = valor
        rules = _load_rules_local()
        if sender not in rules.get("trusted_senders", []):
            rules.setdefault("trusted_senders", []).append(sender)
            _save_rules_local(rules)
        return f"✅ {sender} marcado como CONFIÁVEL.", None, None
    
    if tipo == "spam_remetente":
        sender = valor
        confirm_texto = (
            f"🚫 Bloquear TODOS os futuros emails de:\n*{sender}*?\n\n"
            f"Cria regra permanente e economiza créditos de IA."
        )
        confirm_buttons = [
            {"id": f"confirmar_spam::{sender}", "title": "✅ Sim, Bloquear"},
            {"id": "cancelar", "title": "❌ Cancelar"},
        ]
        return confirm_texto, confirm_buttons, None
    
    if tipo == "confirmar_spam":
        sender = valor
        rules = _load_rules_local()
        if sender not in rules.get("blocked_senders", []):
            rules.setdefault("blocked_senders", []).append(sender)
            _save_rules_local(rules)
        return f"🚫 {sender} BLOQUEADO permanentemente.", None, None
    
    # Mover para pasta (usa LISTA interativa com todas as pastas)
    if tipo == "mover_pasta":
        msg_id = valor
        list_rows = []
        for nome in SUBPASTAS:
            if nome != "Spam":  # Spam não faz sentido aqui
                emoji_map = {
                    "Atencao": "🙋", "Seguranca": "🔒", "Financeiro": "💰",
                    "Bancos": "🏦", "Pessoal": "👤", "Trabalho": "🛠️",
                    "Outros": "📁", "Respostas": "✉️",
                }
                emoji = emoji_map.get(nome, "📁")
                list_rows.append({
                    "id": f"exec_move::{msg_id}::{nome}",
                    "title": f"{emoji} {nome}",
                })
        return "📁 Para qual pasta?", None, list_rows
    
    if tipo == "exec_move":
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
        return f"✅ Movido para {LABEL}/{pasta}.", None, None
    
    return None


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
        
        # Caso 1: Clique em botão ou item de lista
        if msg_type == "interactive":
            interactive = msg.get("interactive", {})
            button_reply = interactive.get("button_reply", {})
            list_reply = interactive.get("list_reply", {})
            
            clicked_id = button_reply.get("id") or list_reply.get("id") or ""
            print(f"👆 Clique: {clicked_id}")
            
            result = handle_button_click(clicked_id, wa_id)
            if result:
                reply_text, reply_buttons, reply_list = result
                if reply_text:
                    success = send_wa(wa_id, reply_text, 
                                      buttons=reply_buttons, 
                                      list_items=reply_list)
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
        reply_result = None
        
        if t in ("ajuda", "help", "?"):
            reply_result = _cmd_ajuda()
        elif t.startswith("verificar"):
            reply_result = _cmd_verificar()
        elif t.startswith("status"):
            reply_result = _cmd_status()
        elif t.startswith(("nao e spam", "não é spam", "nao eh spam")):
            termo = re.sub(r"^(nao e spam|não é spam|nao eh spam)\s*", "",
                           text, flags=re.I).strip()
            reply_result = _cmd_nao_spam(termo)
        elif re.match(r"^mover (.+?) para ([\w\- ]+)$", t):
            m = re.match(r"mover (.+?) para ([\w\- ]+)", t)
            reply_result = _cmd_mover(m.group(1).strip(), 
                                       m.group(2).strip().title().replace(" ", ""))
        elif t.startswith("arquivar"):
            reply_result = _cmd_arquivar(text[len("arquivar"):].strip())
        elif re.match(r"^ultimos (\d+)$", t):
            m = re.match(r"ultimos (\d+)", t)
            reply_result = _cmd_ultimos(m.group(1))
        elif t.startswith("limpar"):
            data_arg = text[len("limpar"):].strip()
            reply_result = _cmd_limpar(data_arg)
        elif t == "lixeira":
            reply_result = _cmd_lixeira()
        elif t.startswith("lixeira esvaziar"):
            reply_result = _cmd_lixeira_esvaziar()
        elif t.startswith("lixeira ") and len(t) > 8:
            termo = text[len("lixeira"):].strip()
            reply_result = _cmd_lixeira(termo)
        else:
            reply_result = _cmd_ajuda()
        
        if reply_result:
            reply_text, reply_buttons, reply_list = reply_result
            print(f"🤖 Reply gerado: {(reply_text or '')[:50]}...")
            if reply_text:
                success = send_wa(wa_id, reply_text, 
                                  buttons=reply_buttons, 
                                  list_items=reply_list)
                print(f"✅ Envio realizado? {success}")
            
        self._resp(200, "ok")
