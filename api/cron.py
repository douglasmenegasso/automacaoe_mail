"""Cron do Vercel: dispara o GitHub Actions a cada 30 min.

Trava de segurança (CRON_SECRET):
- Sem a variável CRON_SECRET configurada: funciona como antes (aberto).
- Com a variável: só dispara com o header "Authorization: Bearer <segredo>".
- Registra os cabeçalhos recebidos no log da Vercel, para conferirmos
  como o cron da própria Vercel se identifica.
"""
import os
import requests
from http.server import BaseHTTPRequestHandler

GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "douglasmenegasso/automacaoe_mail")
GITHUB_WORKFLOW = os.environ.get("GITHUB_WORKFLOW", "automail.yml")
CRON_SECRET = os.environ.get("CRON_SECRET", "")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        print("🔎 Cabeçalhos recebidos em /api/cron:")
        for nome, valor in self.headers.items():
            print(f"   {nome}: {valor}")

        if CRON_SECRET and self.headers.get("Authorization", "") != f"Bearer {CRON_SECRET}":
            print("🚫 Bloqueado: sem segredo válido.")
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"forbidden")
            return

        url = (f"https://api.github.com/repos/{GITHUB_REPO}"
               f"/actions/workflows/{GITHUB_WORKFLOW}/dispatches")
        r = requests.post(
            url,
            headers={"Authorization": f"token {GITHUB_PAT}",
                     "Accept": "application/vnd.github+json"},
            json={"ref": "main",
                  "inputs": {"dry_run": "false", "origem": "cron"}},
        )
        print(f"🔄 GitHub disparado: {r.status_code}")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(f"ok {r.status_code}".encode())

    def do_POST(self):
        self.do_GET()
