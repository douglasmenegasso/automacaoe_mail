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

## Passo a passo de instalação

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

> 💡 Alternativa gratuita para WhatsApp: **Meta WhatsApp Cloud API** (grátis até 1.000 conversas/dia). Se preferir essa opção, me avise que eu adapto o `whatsapp_notifier.py`.

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
