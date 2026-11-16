# Como enviar o código para o GitHub (leia isto primeiro)

## ⚠️ O problema detectado no seu token

Testamos o token `github_pat_11CDRHH2Y0...` exaustivamente e o diagnóstico é claro:

| Operação | Resultado |
|---|---|
| Ler repositórios, ver seu usuário, listar branches | ✅ OK |
| **Escrever** (push, criar commit via API, criar branch, apagar repo) | ❌ 403 — *"Resource not accessible by personal access token"* |

Ou seja: **o token foi criado com escopo somente leitura**. Provavelmente na criação dele a opção
**Repository permissions → Contents** ficou como **"Read-only"** em vez de **"Read and write"**.

> 🔐 **Importante:** por segurança, revogue esse token agora em
> <https://github.com/settings/tokens> (Fine-grained tokens → seu token → Delete/Revoke),
> pois ele foi colado em um chat. Depois gere um novo conforme abaixo.

## ✅ Passo a passo para gerar um token que funciona

1. Acesse <https://github.com/settings/personal-access-tokens/new>
2. Preencha:
   - **Token name:** `automail-push`
   - **Expiration:** 30 days (ou o preferido)
   - **Repository access:** *Only select repositories* → escolha `douglasmenegasso/automacaoe_mail`
3. Em **Permissions**, abra a seção **Repository permissions** e configure:
   - **Contents:** `Read and write`  ← **este é o essencial!**
   - Metadata: Read-only (automático)
4. Clique em **Generate token** e copie o valor (`github_pat_...`).

## 🚀 Enviar o código (duas opções)

### Opção A — Me mande o novo token
Cole aqui o novo token (com Contents: Read and write) e eu executo o push para você.
Tudo já está commitado localmente na branch `main`, pronta para enviar.

### Opção B — Fazer por conta própria no seu computador
```bash
git clone https://github.com/douglasmenegasso/automacaoe_mail.git
cd automacaoe_mail
# copie os arquivos do projeto para cá (main.py, gmail_client.py, analyzer.py,
# whatsapp_notifier.py, settings.py, config.example.json, requirements.txt, README.md, .gitignore)
git add -A
git commit -m "feat: automação de e-mail com IA + alertas WhatsApp"
git push origin main
```
Quando pedir login/senha, use o token como senha (usuário: `douglasmenegasso`).

## 📁 Arquivos prontos para envio (já commitados localmente)

- `main.py` — orquestrador da automação (ler → classificar → agir → notificar)
- `gmail_client.py` — conexão OAuth2 com Gmail
- `analyzer.py` — classificação com IA (spam/propaganda, responder, atenção humana)
- `whatsapp_notifier.py` — alertas via Twilio ou WhatsApp Cloud API (Meta)
- `settings.py` / `config.example.json` — configuração
- `requirements.txt` / `.gitignore` / `README.md`

Nada sensível (tokens, credenciais, `config.json`) será enviado: tudo está no `.gitignore`.
