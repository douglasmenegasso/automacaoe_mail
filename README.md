# 📬 AutoMail

Assistente pessoal que **lê, classifica, organiza e limpa** sua caixa de entrada do Gmail
usando IA, e conversa com você pelo **WhatsApp** (comandos, botões e listas interativas).

> Projeto de uso pessoal/privado. Não é um serviço público.
> Site institucional + política de privacidade: [automail-site](https://douglasmenegasso.github.io/automail-site/)

---

## ✅ Estado atual (produção, sem prazo de expiração)

- Classificação automática a cada **30 min** (seg–sex, 08:00–18:30 BRT) via **Vercel Schedules**.
- Webhook do WhatsApp na **Vercel** com **botões** e **listas roláveis** (janela com seleção).
- IA: **Gemini** (primária) + **Groq** (reserva/failover).
- Spam vai para a pasta **nativa de Spam do Gmail** + etiqueta `AutoMail/Spam`.
- **Limpeza em massa por data** (lixeira **ou** permanente) executada no **GitHub Actions**.
- **Lixeira** consultável pelo bot (10 mais recentes) com opção **Recuperar**.
- `status` **dinâmico** (lê as pastas reais do Gmail em tempo real).
- OAuth do Gmail **publicado ("Em produção")** + **refresh token duradouro** com escopo total.
- Nome de exibição do número **aprovado** na Meta. App Meta **Live**.
- Backlog reduzido de ~17.000 para ~6.900 e-mails.

---

## 🏗️ Arquitetura

    ┌────────────┐   cron 30min    ┌──────────────┐  workflow_dispatch  ┌─────────────────┐
    │   Vercel   │ ──────────────► │  api/cron.py │ ──────────────────► │ GitHub Actions  │
    │ (Schedules)│                 └──────────────┘                     │  automail.yml   │
    └────────────┘                                                      │   → main.py     │
          ▲                                                             └────────┬────────┘
          │ webhook (mensagens/botões)                                           │
    ┌─────┴────────┐   workflow_dispatch (limpar)   ┌─────────────────┐          │
    │ api/webhook  │ ─────────────────────────────► │  cleanup.yml    │          │
    │   (Vercel)   │                                │   → cleanup.py  │          │
    └─────┬────────┘                                └────────┬────────┘          │
          │                                                  │                   │
          ▼                                                  ▼                   ▼
    ┌────────────                                    ┌────────────┐      ┌────────────┐
    │  WhatsApp  │◄───────────────────────────────────│  Gmail API │◄─────│ Gemini/Groq│
    │ (Meta API) │        notificações / comandos     │ (escopo    │      │ (classif.) │
    └────────────┘                                    │  total)    │      └────────────┘
                                                      └────────────┘

**Por que essa divisão?**
- O webhook da Vercel tem **teto de 30 s**. Trabalho pesado (apagar milhares de e-mails)
  **não** roda nele: o webhook apenas **agenda** e o **GitHub Actions** executa sem teto.
- O cron nativo do GitHub é instável; por isso o **relógio** mora no **Vercel Schedules**
  e o GitHub só **executa** quando disparado.

---

## 📁 Estrutura do repositório

    automacaoe_mail/
    ├── main.py                  # orquestra: lê Gmail → classifica → age → notifica
    ├── analyzer.py              # prompt + chamada de IA (Gemini/Groq)
    ├── ai_router.py             # roteamento/failover entre IAs
    ├── gmail_client.py          # credencial OAuth (lê GMAIL_TOKEN; não repassa SCOPES no refresh)
    ├── whatsapp_notifier.py     # envio de mensagens/notificações (Meta Cloud API)
    ├── cleanup.py               # exclusão em massa por data (roda no Actions)
    ├── settings.py              # carrega config.json / CONFIG_JSON
    ├── config.example.json      # modelo de configuração
    ├── rules.json               # regras de remetentes (bloqueados/confiáveis)
    ├── requirements.txt
    ├── vercel.json              # funções + Schedules (cron) + maxDuration
    ├── api/
    │   ├── webhook.py           # comandos, botões, listas; agenda limpeza; lixeira/recuperar
    │   └── cron.py              # dispara automail.yml quando o Vercel chama
    └── .github/workflows/
        ├── automail.yml         # workflow_dispatch → main.py
        └── cleanup.yml          # workflow_dispatch (inputs: date, mode) → cleanup.py

Repo irmão (público, GitHub Pages): **`automail-site`** → `index.html` + `privacidade.html`
(usados como página inicial e política de privacidade do OAuth no Google).

---

## 💬 Comandos do WhatsApp

| Comando | O que faz |
|---|---|
| `ajuda` | Menu com botões: Ações rápidas / Lixeira / Todos comandos |
| `verificar` | Dispara análise manual agora (`automail.yml`) |
| `status` | Conta e-mails por pasta, lendo o Gmail em tempo real |
| `ultimos <n>` | Lista os últimos n e-mails |
| `nao e spam <termo>` | Tira do Spam e devolve à entrada |
| `mover <termo> para <pasta>` | Move e-mail (ou abre lista rolável de pastas) |
| `arquivar <termo>` | Arquiva e-mail |
| `limpar <dd/mm/aaaa>` | Confirma com botões (Lixeira / Permanente / Cancelar) e **agenda** a limpeza no Actions |
| `lixeira` | Lista os 10 mais recentes da lixeira; item → **Recuperar** / Voltar |

**Comportamentos importantes:**
- A confirmação do `limpar` mostra no máx. **500** (1ª página); o **total real** aparece na
  mensagem "🔄 Exclusão agendada". O `cleanup.py` apaga em lotes de 500 **até esvaziar**.
- `404` durante exclusão = mensagem **já excluída** (retry duplicado) → contado como
  "já haviam sido excluídos", **não** como erro.
- Exclusão **definitiva da lixeira** é feita no Gmail (o bot não oferece, para evitar 403).
- O Gmail na tela conta **conversas (threads)**; a API conta **mensagens** → os números
  diferem (ex.: 405 mensagens = 396 conversas). Isso é normal.
- Cada e-mail recebe a etiqueta **pai `AutoMail`** + a **sub-etiqueta** da categoria
  (a "dupla chip" é proposital: a pai é usada nas buscas do bot).

---

## 🧠 Classificação

| Categoria | Ação |
|---|---|
| `spam_propaganda` | Marca **SPAM nativo** + etiqueta `AutoMail/Spam` |
| `responde_se` | Resposta automática (se habilitada) + `AutoMail/Respostas` |
| `precisa_humano` | Notifica no WhatsApp + `AutoMail/<pasta>` |

Sempre aplica a etiqueta pai `AutoMail` e remove etiquetas duplicadas/antigas.
Pastas padrão: `Spam, Atencao, Seguranca, Financeiro, Bancos, Pessoal, Trabalho, Outros,
Respostas, Contas, Vagas` (o `status` descobre novas pastas automaticamente).

---

## 🔐 Segredos (GitHub Secrets **e** Vercel Env)

| Segredo | Uso |
|---|---|
| `GMAIL_TOKEN` | JSON OAuth duradouro: `{token, refresh_token, token_uri, client_id, client_secret, scopes:["https://mail.google.com/"]}` |
| `CONFIG_JSON` | Configurações do projeto (gera `config.json` no Actions) |
| `GEMINI_API_KEY` / `GROQ_API_KEY` | IA primária / reserva |
| `META_WA_ACCESS_TOKEN` | Token **permanente** do System User (Meta) |
| `META_WA_PHONE_NUMBER_ID` | ID do número de produção |
| `WEBHOOK_VERIFY_TOKEN` | Verificação do webhook |
| `GITHUB_PAT` | Vercel/webhook disparar workflows |
| `TWILIO_*` / `INFOBIP_API_KEY` | Canais alternativos |

**OAuth Google:** projeto nº `174044064229` (Gmail API **ativada**); cliente Web `automail`;
`client_id 174044064229-c1n39n909foua6ce28j7e3t0t7u95clg.apps.googleusercontent.com`;
redirect `https://developers.google.com/oauthplayground`; status **Em produção**.

---

## ⚙️ Setup (resumo)

1. **Google Cloud:** projeto → ativar **Gmail API** → cliente OAuth **Web** com redirect do
   Playground → tela de consentimento (Externo) → adicionar seu e-mail como teste →
   **Publicar app** (Em produção).
2. **Token:** OAuth Playground com "use your own credentials" → scope
   `https://mail.google.com/` → Authorize → Exchange → montar o JSON `GMAIL_TOKEN`.
3. **Meta:** app Live, número com nome aprovado, **System User token** permanente,
   webhook apontando para `https://<projeto>.vercel.app/api/webhook`.
4. **Vercel:** importar repo, colar Env, deploy; Schedules chamando `/api/cron`.
5. **GitHub:** colar os mesmos Secrets; workflows já no repo.

---

## 🚨 Troubleshooting (erros reais já resolvidos)

| Erro | Causa | Correção |
|---|---|---|
| `403 insufficient authentication scopes` | token sem escopo p/ ação (delete exige `mail.google.com/`) | re-gerar token com escopo total |
| `403 accessNotConfigured` / "Gmail API has not been used in project X" | Gmail API desativada naquele projeto | ativar a API no projeto do client_id |
| `401 invalid_client` / "client secret is invalid" | `client_secret` errado no Playground (é `GOCSPX-…`, não o nome do app) | colar o secret correto |
| `RefreshError invalid_scope` | forçar `SCOPES` no refresh | não repassar escopos (gmail_client já corrigido) |
| `404 Requested entity was not found` no delete | mensagem já excluída (retry) | contar como "já excluído" |
| Webhook mudo + `POST 500 FUNCTION_INVOCATION_FAILED` | exceção em comando que toca Gmail (token/JSON) | ver última linha do traceback na Vercel |
| `DEPLOYMENT_NOT_FOUND` em `*.vercel.app` | hostname sem deploy ligado | estáticos/branding no **GitHub Pages** |
| `131037` | nome de exibição não aprovado | (já resolvido: nome aprovado) |
| `190/401` Meta | token inválido/expirado | usar System User permanente |
| `jitter exceeds cadence` | schedule < 15 min no Hobby | usar ≥ 15 min |

---

## ⚠️ Limites (planos gratuitos)

- Vercel webhook: **maxDuration 30 s** → pesado vai pro Actions.
- Vercel Schedules: mínimo **15 min**; cron legado 1x/dia (não usar).
- GitHub cron nativo: instável (desativado).
- Meta: janela **24 h** para responder; System User token não expira.
- OAuth em **Testing**: refresh expira em **7 dias** → manter **Em produção**.
- Gmail: `gmail.modify` **não** permite exclusão permanente; exige `mail.google.com/`.

---

## 🗺️ Roadmap

- [ ] Persistir regras de remetentes fora do `/tmp` volátil da Vercel
- [ ] Comando `responder` (enviar e-mail pelo WhatsApp)
- [ ] Resumo inteligente com **ação sugerida** nas notificações
- [ ] Comandos por **áudio** no WhatsApp
- [ ] `CRON_SECRET` protegendo `/api/cron`
- [ ] Evolução multi-cliente / multi-provedor (Graph + IMAP) com isolamento por conta

---

## 📜 Histórico recente

- Botões + listas roláveis no WhatsApp; `status` dinâmico.
- `limpar` por data e `lixeira`/recuperar via GitHub Actions (`cleanup.yml` + `cleanup.py`).
- OAuth publicado + token duradouro; `gmail_client.py` corrigido; Gmail API ativada.
- Site de branding no GitHub Pages; backlog ~17k → ~6.9k.

---

## 📄 Licença / uso

Uso pessoal e privado de Douglas Menegasso. Sem garantia. Não redistribuir segredos.
