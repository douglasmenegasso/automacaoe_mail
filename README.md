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
