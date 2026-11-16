# 📬 Automação de E-mail: Gmail + IA + WhatsApp

Automação que:
1. **Lê seus e-mails** da caixa de entrada do Gmail;
2. **Classifica com IA** (OpenAI) em três categorias:
   - 🗑️ `spam_propaganda` → **apaga** (vai para a lixeira) ou arquiva;
   - ✉️ `responde_se` → **responde automaticamente** na mesma thread;
   - 🙋 `precisa_humano` → envia um **alerta no seu WhatsApp** com resumo do assunto e o que você precisa fazer;
3. Pode rodar automaticamente todo dia via **cron**.

## Arquivos

| Arquivo | Função |
|---|---|
| `main.py` | Orquestra tudo (ler → analisar → agir → notificar) |
| `gmail_client.py` | Autenticação OAuth2 e leitura/ação no Gmail |
| `analyzer.py` | Classificação por IA (+ fallback heurístico sem IA) |
| `whatsapp_notifier.py` | Envio via Twilio, Infobip ou console (teste) |
| `settings.py` / `config.example.json` | Configuração |

## Onde executar / hospedar

A automação **não está hospedada em lugar nenhum automaticamente** — ela roda
onde você escolher. Opções, da mais simples à mais robusta:

| Opção | Custo | Como |
|---|---|---|
| 🖥️ Seu próprio computador | Grátis | Rode `python main.py` manualmente ou agende com cron/Agendador de Tarefas (passo 7 abaixo). Só precisa estar ligado nos horários agendados. |
| 🌤️ Google Cloud Run Jobs / Functions | Quase grátis (crédito mensal) | Ideal: é o mesmo ecossistema do Gmail. Faça deploy da imagem Docker e agende com Cloud Scheduler. |
| ⚡ GitHub Actions (cron) | Grátis para contas públicas/2000 min/mês | Commit do código num repo privado + workflow `.github/workflows/automail.yml` agendado; as chaves ficam em *Settings → Secrets*. |
| 🐚 VPS barata (Contabo, DigitalOcean, Hetzner ~US$4–6/mês) | Baixo | Rode 24/7 com cron; você acessa via SSH. |
| 🔗 Make / n8n self-hosted | Baixo/médio | Alternativa visual, mas exige adaptar a lógica de IA. |

Recomendação prática: comece **no seu computador** (seco/cron local) até confiar
nas classificações; depois migre para **GitHub Actions** ou **Cloud Run** para
rodar 24/7 sem depender da sua máquina.

## ☁️ Hospedagem no GitHub Actions (configurado neste repositório)

O repositório já inclui o workflow [`.github/workflows/automail.yml`](.github/workflows/automail.yml), que roda a automação automaticamente **2ª a 6ª às 08:00 e 18:00 (Brasília)**, sem servidor.

**Passo a passo:**

1. Autorize o Gmail **uma vez na sua máquina**: `python gmail_client.py --login` (gera `token.json`).
2. Gere o token em base64: `base64 -w0 token.json` (Linux/macOS).
3. No GitHub → repositório → **Settings → Secrets and variables → Actions → New repository secret**, crie:

| Secret | Obrigatório | Conteúdo |
|---|---|---|
| `GMAIL_TOKEN_B64` | ✅ | Resultado do `base64 -w0 token.json` |
| `CONFIG_JSON` | ✅ | Conteúdo inteiro do seu `config.json` |
| `OPENAI_API_KEY` | ✅ | Chave da OpenAI |
| `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` | se provider=twilio | Credenciais Twilio |
| `META_WA_ACCESS_TOKEN` + `META_WA_PHONE_NUMBER_ID` | se provider=meta | WhatsApp Cloud API (grátis) |
| `INFOBIP_API_KEY` | se provider=infobip | Credencial Infobip |

4. Teste sem efeitos colaterais: **Actions → automail → Run workflow → marque `dry_run`**.
5. Para rodar de verdade manualmente: mesmo botão com `dry_run` desmarcado.

> ⚠️ **Nunca commite** `credentials.json`, `token.json`, `config.json` nem chaves de API — eles já estão no `.gitignore`. As credenciais vivem apenas nos Secrets do GitHub.

## Passo a passo de instalação (local)

### 1. Instalar dependências
```bash
pip install -r requirements.txt
```

### 2. Configurar o Gmail (OAuth2)
1. Acesse [Google Cloud Console](https://console.cloud.google.com/) e crie um projeto.
2. Em *APIs e serviços*, ative a **Gmail API**.
3. Configure a **tela de consentimento OAuth** (tipo "Externo"; adicione seu e-mail como *test user* enquanto estiver em modo de teste).
4. Em *Credenciais*, crie uma credencial OAuth do tipo **Desktop app** e baixe o JSON.
5. Salve o JSON como `credentials.json` nesta pasta.
6. Autorize (só na primeira vez, abre o navegador):
```bash
python gmail_client.py --login   # gera o token.json
```

### 3. Criar o config.json
```bash
cp config.example.json config.json
```
Ajuste:
- `automation.notify_email` — seu e-mail;
- `automation.auto_reply_enabled` — deixe `true` só quando confiar nas respostas automáticas;
- `whatsapp.provider` — `twilio`, `infobip` ou `console` (para testar sem custo);
- `whatsapp.*.to_number` — **o seu número de WhatsApp** com código do país (ex.: `whatsapp:+5511999999999`).

### 4. Chaves de API (variáveis de ambiente)
```bash
export OPENAI_API_KEY="sua-chave-openai"
export TWILIO_ACCOUNT_SID="..."     # se usar Twilio
export TWILIO_AUTH_TOKEN="..."
# ou
export INFOBIP_API_KEY="..."        # se usar Infobip
```

> 💡 Alternativa gratuita: **Meta WhatsApp Cloud API** (grátis até 1.000 conversas/dia) — já implementada! Basta escolher `"provider": "meta"` no config.json e criar um app WhatsApp em [developers.facebook.com](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started), depois:
> ```bash
> export META_WA_ACCESS_TOKEN="..."       # token do número de teste (24h) ou permanente (System User)
> export META_WA_PHONE_NUMBER_ID="..."    # ID do Phone Number no painel da Meta
> ```
> ⚠️ Na API da Meta, para enviar mensagens livres o seu número precisa ter mandado mensagem ao número do bot nas últimas 24h (ou usar templates aprovados). Para uso pessoal, basta mandar um "oi" uma vez por dia ao número do sandbox.

### 5. Testar SEM executar ações (muito recomendado!)
```bash
python main.py --dry-run
```
Mostra como cada e-mail seria classificado, sem apagar/nada.

### 6. Rodar de verdade
```bash
python main.py
```

### 7. Agendar execução automática (Linux/macOS — cron)
```bash
crontab -e
# todos os dias às 8h e 18h:
0 8,18 * * * cd /caminho/para/este/projeto && /usr/local/bin/python3 main.py >> automail.log 2>&1
```
(No Windows use o *Agenciador de Tarefas*; na nuvem, GitHub Actions ou Google Cloud Functions também funcionam.)

## Segurança e boas práticas
- O spam é movido para a **lixeira** (`trash`), não apagado definitivamente — você pode recuperar por 30 dias.
- As respostas automáticas **nunca inventam dados** (datas, valores); se depender de informação sua, vira alerta no WhatsApp.
- `credentials.json`, `token.json` e `config.json` estão no `.gitignore` — **não os compartilhe**.
- Comece com `auto_reply_enabled: false` e `--dry-run`; só habilite a resposta automática depois de validar as classificações por alguns dias.

## Como funciona a decisão
O prompt em `analyzer.py` pede à IA um JSON com `categoria`, `motivo`, `resposta` e `resumo_para_whatsapp`. Você pode refinar as regras editando o `SYSTEM_PROMPT` (ex.: nunca apagar e-mails de bancos, sempre avisar sobre cobranças etc.). Sugiro adicionar suas regras pessoais aí — me diga quais critérios você quer e eu ajusto!
