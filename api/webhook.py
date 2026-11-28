"""Webhook do WhatsApp (Fase C+): recebe mensagens, interpreta comandos E cliques de botões."""
import json
import os
import re
import unicodedata
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from rules_store import load_rules, save_rules

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
             "Pessoal", "Trabalho", "Outros", "Respostas", "Contas", "Vagas"]


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


def _latest(service, q, label_ids=None):
    kwargs = {"userId": "me", "maxResults": 1}
    if q:
        kwargs["q"] = q
    if label_ids:
        kwargs["labelIds"] = label_ids
    resp = service.users().messages().list(**kwargs).execute()
    ids = resp.get("messages", [])
    return ids[0]["id"] if ids else None


def _modify(service, mid, add=None, remove=None):
    body = {}
    if add:
        body["addLabelIds"] = add
    if remove:
        body["removeLabelIds"] = remove
    service.users().messages().modify(userId="me", id=mid, body=body).execute()


def _sem_acento(s: str) -> str:
    """Remove acentos para comparar comandos ('não é spam' vira 'nao e spam')."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def send_wa(to, text, buttons=None, list_items=None, header="", footer=""):
    """Envia mensagem com botões OU lista interativa (janela com seleção)."""
    print(f"📤 Tentando enviar para {to}: {text[:30]}...")

    payload = {"messaging_product": "whatsapp", "to": to}

    if list_items and len(list_items) > 0:
        rows = []
        for item in list_items[:10]:
            row = {"id": item["id"], "title": item["title"][:24]}
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
                    "sections": [{"rows": rows}]
                }
            }
        })
    elif buttons and len(buttons) > 0:
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
        payload.update({"type": "text", "text": {"body": text}})

    r = requests.post(
        f"https://graph.facebook.com/{META_API}/{META_PHONE_ID}/messages",
        headers={"Authorization": f"Bearer {META_TOKEN}"},
        json=payload,
    )
    print(f"📥 Resposta do envio: {r.status_code} - {r.text}")
    return r.ok


# ============================================================
# FUNÇÕES AUXILIARES DINÂMICAS
# ============================================================

def _descobrir_pastas(service):
    """Lê as etiquetas do Gmail e retorna só as sub-pastas de AutoMail."""
    resp = service.users().labels().list(userId="me").execute()
    pastas_encontradas = []
    for lb in resp.get("labels", []):
        nome = lb["name"]
        if nome.startswith(f"{LABEL}/"):
            pasta_nome = nome.split("/", 1)[1]
            pastas_encontradas.append((pasta_nome, nome))
    return sorted(pastas_encontradas)


def _query_limpeza(data_str):
    """Query canônica de exclusão: TODOS da entrada antes da data (classificados ou não)."""
    from datetime import datetime
    dt_limit = datetime.strptime(data_str.strip(), "%d/%m/%Y")
    query_date = dt_limit.strftime("%Y/%m/%d")
    return f"in:inbox before:{query_date}"


# ============================================================
# COMANDOS PRINCIPAIS
# ============================================================

def _cmd_ajuda():
    texto = "🤖 *AUTOMAIL*\nComo posso ajudar?"
    buttons = [
        {"id": "menu_acoes", "title": "⚡ Ações rápidas"},
        {"id": "menu_lixeira", "title": "🗑️ Lixeira"},
        {"id": "menu_comandos", "title": "📋 Todos comandos"},
    ]
    return texto, buttons, None


def _cmd_menu_acoes():
    texto = "⚡ *AÇÕES RÁPIDAS*"
    buttons = [
        {"id": "cmd_verificar", "title": "🔄 Analisar agora"},
        {"id": "cmd_status", "title": "📊 Ver status"},
        {"id": "cmd_ultimos::5", "title": "📥 Últimos 5"},
    ]
    return texto, buttons, None


def _cmd_menu_comandos():
    """Lista de comandos no formato JANELA COM SELEÇÃO (list message)."""
    texto = "📋 Escolha um comando na lista:"
    list_rows = [
        {"id": "cmd_verificar", "title": "🔄 Verificar", "description": "Analisa a caixa agora"},
        {"id": "cmd_status", "title": "📊 Status", "description": "Resumo das pastas"},
        {"id": "cmd_ultimos::5", "title": "📥 Últimos 5", "description": "Lista os 5 recentes"},
        {"id": "menu_lixeira", "title": "🗑️ Lixeira", "description": "Ver / recuperar recentes"},
        {"id": "cmd_naospam", "title": "✅ Não é spam", "description": "Tira do Spam (precisa termo)"},
        {"id": "cmd_mover_help", "title": "📁 Mover", "description": "Move email (termo + pasta)"},
        {"id": "cmd_arquivar_help", "title": "🗃️ Arquivar", "description": "Tira da entrada (precisa termo)"},
        {"id": "cmd_limpar_help", "title": "🧹 Limpar por data", "description": "Lixeira ou permanente"},
    ]
    return texto, None, list_rows


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


def _cmd_status():
    s = _gmail()
    pastas = _descobrir_pastas(s)

    if not pastas:
        return "📊 *Status*\n━━━━━━━━━━━━━━━━━━\nNenhuma pasta encontrada.", None, None

    linhas = []
    total = 0
    for nome_pasta, nome_label_completo in pastas:
        q = f'label:"{nome_label_completo}" -in:sent -in:chat'
        resp = s.users().messages().list(userId="me", q=q, maxResults=500).execute()
        count = len(resp.get("messages", []))
        linhas.append(f"• {nome_pasta}: {count}")
        total += count

    texto = f"📊 *Status* (total: {total})\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(linhas)
    return texto, None, None


def _cmd_nao_spam(termo):
    """Busca no SPAM inteiro (nativo do Gmail + AutoMail/Spam) e devolve à entrada."""
    s = _gmail()
    q = "in:spam"
    if termo:
        q += f" {termo}"
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei no Spam com esse termo.", None, None
    spam_nativo = _label_id(s, "SPAM")
    spam_automail = _label_id(s, f"{LABEL}/Spam")
    aten_id = _label_id(s, f"{LABEL}/Atencao", create=True)
    remover = [lid for lid in (spam_nativo, spam_automail) if lid]
    _modify(s, mid, add=[aten_id, "INBOX"], remove=remover)
    return "✅ Tirado do Spam, devolvido pra entrada (AutoMail/Atencao).", None, None


def _cmd_mover(termo, pasta):
    """Busca na caixa inteira (exceto lixeira, enviados e spam) e move para a pasta."""
    s = _gmail()
    base = "-in:trash -in:sent -in:chat -in:spam"
    q = f"{termo} {base}" if termo else base
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei com esse termo.", None, None
    pai = _label_id(s, LABEL, create=True)
    alvo = _label_id(s, f"{LABEL}/{pasta}", create=True)
    remove = []
    for nome in SUBPASTAS:
        lid = _label_id(s, f"{LABEL}/{nome}")
        if lid and lid != alvo:
            remove.append(lid)
    _modify(s, mid, add=[alvo, pai], remove=remove)
    return f"✅ Movido para {LABEL}/{pasta}.", None, None


def _cmd_arquivar(termo):
    """Busca na caixa inteira (exceto lixeira, enviados e spam) e tira da entrada."""
    s = _gmail()
    base = "-in:trash -in:sent -in:chat -in:spam"
    q = f"{termo} {base}" if termo else base
    mid = _latest(s, q)
    if not mid:
        return "🤷 Não achei com esse termo.", None, None
    _modify(s, mid, remove=["INBOX"])
    return "✅ Arquivado.", None, None


def _cmd_ultimos(n):
    s = _gmail()
    pai = _label_id(s, LABEL)
    if not pai:
        return "🤷 Nenhuma pasta AutoMail encontrada ainda.", None, None
    resp = s.users().messages().list(userId="me", labelIds=[pai],
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


# ============================================================
# LIMPEZA POR DATA (Lixeira OU Permanente — ambos funcionam)
# ============================================================

def _cmd_limpar(data_str):
    """Pergunta o tipo de exclusão (lixeira ou permanente) antes de executar."""
    try:
        from datetime import datetime
        datetime.strptime(data_str.strip(), "%d/%m/%Y")
    except ValueError:
        return "❌ Data inválida. Use dd/mm/aaaa. Ex: limpar 01/01/2024", None, None

    s = _gmail()
    q = _query_limpeza(data_str)

    resp = s.users().messages().list(userId="me", q=q, maxResults=500).execute()
    ids = resp.get("messages", [])

    if not ids:
        return f"🤷 Nenhum email na caixa de entrada antes de {data_str}.", None, None

    confirm_texto = (
        f"⚠️ *ATENÇÃO*\n"
        f"Encontrei {len(ids)} emails DA CAIXA DE ENTRADA anteriores a {data_str}.\n"
        f"(Inclui emails NÃO classificados — o backlog antigo.)\n\n"
        f"Como deseja excluir?"
    )
    buttons = [
        {"id": f"limpar_trash::{data_str}", "title": "♻️ Ir pra Lixeira"},
        {"id": f"limpar_perm::{data_str}", "title": "💀 Exclusão Permanente"},
        {"id": "cancelar", "title": "❌ Cancelar"},
    ]
    return confirm_texto, buttons, None


def _executar_limpar(data_str, modo):
    """Agenda a exclusão no GitHub Actions e avisa na hora; o Actions notifica ao concluir."""
    s = _gmail()
    q = _query_limpeza(data_str)

    total = 0
    page = None
    while True:
        kwargs = {"pageToken": page} if page else {}
        resp = s.users().messages().list(
            userId="me", q=q, maxResults=500, **kwargs).execute()
        total += len(resp.get("messages", []))
        page = resp.get("nextPageToken")
        if not page:
            break

    if total == 0:
        return f"🤷 Nenhum email na caixa de entrada antes de {data_str}.", None, None

    r = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}"
        f"/actions/workflows/cleanup.yml/dispatches",
        headers={"Authorization": f"token {GITHUB_PAT}",
                 "Accept": "application/vnd.github+json"},
        json={"ref": "main", "inputs": {"date": data_str, "mode": modo}},
    )
    if r.status_code in (200, 204):
        emoji = "♻️" if modo == "trash" else "💀"
        modo_txt = "Lixeira" if modo == "trash" else "Permanente"
        return (
            f"🔄 *Exclusão agendada*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{total} emails anteriores a {data_str}\n"
            f"Modo: {modo_txt} {emoji}\n\n"
            f"Vou te avisar aqui quando concluir."
        ), None, None
    return f"⚠️ Falha ao agendar ({r.status_code})", None, None

# ============================================================
# LIXEIRA (só os mais recentes + recuperar; definitivo é no Gmail)
# ============================================================

def _cmd_lixeira(termo=""):
    s = _gmail()
    q = "in:trash"
    if termo:
        q += f" {termo}"

    resp = s.users().messages().list(userId="me", q=q, maxResults=10).execute()
    items = resp.get("messages", [])

    if not items:
        return "🗑️ Lixeira vazia (ou sem resultados pro termo).", None, None

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

    texto = ("🗑️ Os 10 mais recentes da lixeira.\n"
             "Lista completa e exclusão definitiva: abra o Gmail.")
    return texto, None, list_rows


def _cmd_lixeira_item(msg_id):
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
        {"id": "cmd_lixeira", "title": "↩️ Voltar"},
    ]
    return texto, buttons, None


# ============================================================
# INTERPRETADOR DE CLIQUES EM BOTÕES / LISTAS
# ============================================================

def handle_button_click(button_id: str, wa_id: str):
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

    # Comandos que precisam de argumento: orientam como digitar
    if tipo == "cmd_naospam":
        return "✍️ Digite: nao e spam <termo>\nEx: nao e spam nubank", None, None
    if tipo == "cmd_mover_help":
        return "✍️ Digite: mover <termo> para <pasta>\nEx: mover nubank para Bancos", None, None
    if tipo == "cmd_arquivar_help":
        return "✍️ Digite: arquivar <termo>\nEx: arquivar promo", None, None
    if tipo == "cmd_limpar_help":
        return "✍️ Digite: limpar <dd/mm/aaaa>\nEx: limpar 31/12/2020", None, None

    # Limpeza por data (escolha do destino)
    if tipo == "limpar_trash":
        return _executar_limpar(valor, "trash")
    if tipo == "limpar_perm":
        return _executar_limpar(valor, "perm")

    # Lixeira (só recuperar; exclusão definitiva é no Gmail)
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

    # Regras de remetentes (agora persistidas no GitHub via rules_store)
    if tipo == "seguro":
        sender = valor
        rules = load_rules()
        if sender not in rules.get("trusted_senders", []):
            rules.setdefault("trusted_senders", []).append(sender)
            save_rules(rules)
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
        rules = load_rules()
        if sender not in rules.get("blocked_senders", []):
            rules.setdefault("blocked_senders", []).append(sender)
            save_rules(rules)
        return f"🚫 {sender} BLOQUEADO permanentemente.", None, None

    # Mover para pasta (LISTA dinâmica)
    if tipo == "mover_pasta":
        msg_id = valor
        s = _gmail()
        pastas = _descobrir_pastas(s)
        emoji_map = {
            "Atencao": "🙋", "Seguranca": "🔒", "Financeiro": "💰",
            "Bancos": "🏦", "Pessoal": "👤", "Trabalho": "🛠️",
            "Outros": "📁", "Respostas": "✉️", "Contas": "🧾", "Vagas": "💼",
        }
        list_rows = []
        for nome_pasta, _ in pastas:
            if nome_pasta.lower() == "spam":
                continue
            emoji = emoji_map.get(nome_pasta, "📁")
            list_rows.append({
                "id": f"exec_move::{msg_id}::{nome_pasta}",
                "title": f"{emoji} {nome_pasta}",
                "description": f"Mover para {nome_pasta}",
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


# ============================================================
# HANDLER HTTP
# ============================================================

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

        stripped = text.strip()
        t = stripped.lower()
        tn = _sem_acento(t)
        reply_result = None

        if tn in ("ajuda", "help", "?"):
            reply_result = _cmd_ajuda()
        elif tn.startswith("verificar"):
            reply_result = _cmd_verificar()
        elif tn.startswith("status"):
            reply_result = _cmd_status()
        elif tn.startswith(("nao e spam", "nao eh spam")):
            prefix_len = len("nao e spam") if tn.startswith("nao e spam") else len("nao eh spam")
            termo = stripped[prefix_len:].strip()
            reply_result = _cmd_nao_spam(termo)
        elif re.match(r"^mover (.+?) para ([\w\- ]+)$", t):
            m = re.match(r"mover (.+?) para ([\w\- ]+)", t)
            pasta = _sem_acento(m.group(2).strip()).title().replace(" ", "")
            reply_result = _cmd_mover(m.group(1).strip(), pasta)
        elif tn.startswith("arquivar"):
            reply_result = _cmd_arquivar(stripped[len("arquivar"):].strip())
        elif re.match(r"^ultimos (\d+)$", tn):
            m = re.match(r"ultimos (\d+)", tn)
            reply_result = _cmd_ultimos(m.group(1))
        elif tn.startswith("limpar"):
            data_arg = stripped[len("limpar"):].strip()
            reply_result = _cmd_limpar(data_arg)
        elif tn == "lixeira":
            reply_result = _cmd_lixeira()
        elif tn.startswith("lixeira ") and len(tn) > 8:
            termo = stripped[len("lixeira"):].strip()
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
