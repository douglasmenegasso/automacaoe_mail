# Como enviar o código para o GitHub

O repositório de destino é: **https://github.com/douglasmenegasso/automacaoe_mail**

O `git push` exige autenticação da **sua conta do GitHub**, que não pode ser
feita por mim (por segurança, nunca compartilhe sua senha). Escolha UMA das
opções abaixo e rode na sua máquina.

---

## Opção A — Personal Access Token (recomendada)

1. Gere um token em: https://github.com/settings/tokens/new
   - Marque a escopo **`repo`** (full control of private repositories)
   - Copie o token gerado (começa com `ghp_...`)

2. No terminal, dentro da pasta do projeto:

```bash
git remote add origin https://github.com/douglasmenegasso/automacaoe_mail.git
git push origin master:main
```

Quando aparecer `Password for ...`, **cole o token** (não a senha do GitHub).

### Alternativa com credencial salva (evita digitar toda vez)

```bash
git config --global credential.helper store   # Linux/Mac
# Windows: git config --global credential.helper manager
git push origin master:main
# usuário: douglasmenegasso | senha: cole o token ghp_...
```

---

## Opção B — GitHub CLI (mais simples se você tiver o `gh` instalado)

```bash
# instale: https://cli.github.com/
gh auth login          # faça login pelo navegador
cd /caminho/do/projeto
git remote add origin https://github.com/douglasmenegasso/automacaoe_mail.git
git push origin master:main
```

---

## Opção C — Chave SSH

```bash
ssh-keygen -t ed25519 -C "seu@email.com"
cat ~/.ssh/id_ed25519.pub   # copie e cole em https://github.com/settings/keys
git remote set-url origin git@github.com:douglasmenegasso/automacaoe_mail.git
git push origin master:main
```

---

## Observações importantes

- O branch local chama **`master`**; no GitHub o padrão é **`main`**.
  O comando `git push origin master:main` resolve isso automaticamente.
- O repositório remoto tem apenas um `README.md` inicial; o histórico local
  já foi mesclado com ele (commit de merge), então o push não será rejeitado.
- Arquivos sensíveis (`credentials.json`, `token.json`, `config.json`, `.env`)
  estão no `.gitignore` e **não** serão enviados. Nunca os faça upload.
- Se preferir subir tudo de uma vez sem git local, você também pode arrastar
  os arquivos direto na interface do GitHub (Add file → Upload files).
