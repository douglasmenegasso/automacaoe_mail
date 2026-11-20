"""Cron do Vercel: dispara o GitHub Actions a cada 30 min."""
import os
import requests
from http.server import BaseHTTPRequestHandler

GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "douglasmenegasso/automacaoe_mail")
GITHUB_WORKFLOW = os.environ.get("GITHUB_WORKFLOW", "automail.yml")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = (f"https://api.github.com/repos/{GITHUB_REPO}"
               f"/actions/workflows/{GITHUB_WORKFLOW}/dispatches")
        r = requests.post(
            url,
            headers={"Authorization": f"token {GITHUB_PAT}",
                     "Accept": "application/vnd.github+json"},
            json={"ref": "main", "inputs": {"dry_run": "false"}},
        )
        print(f"🔄 GitHub disparado: {r.status_code}")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(f"ok {r.status_code}".encode())

    def do_POST(self):
        self.do_GET()
