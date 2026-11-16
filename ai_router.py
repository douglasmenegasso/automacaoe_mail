"""Roteador de IA com failover: Gemini -> Groq -> (heurística no analyzer).

Usa o SDK da OpenAI apontando para os endpoints compatíveis de cada provedor.
A ordem e os modelos vêm do config.json (bloco "ai"), então trocar de modelo
no futuro = editar 1 linha do config, sem mexer em código.
"""

import json
import os
import re

from openai import OpenAI

# Provedores que estouraram a cota NESTA execução (não tenta de novo neles)
_esgotados = set()


class SemProvedorError(Exception):
    """Todos os provedores de IA falharam (o analyzer deve cair na heurística)."""


def _eh_erro_de_cota(exc) -> bool:
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None)
    return (
        status == 429
        or "429" in msg
        or "resource_exhausted" in msg
        or "quota" in msg
        or "rate limit" in msg
        or "rate_limit" in msg
    )


def _extrair_json(texto: str):
    """Parsing tolerante: aceita JSON puro ou cercado por markdown/texto."""
    texto = (texto or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", texto, re.DOTALL)
    if m:
        texto = m.group(1).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError("Resposta da IA nao contem JSON valido")


def chat(system_prompt: str, user_prompt: str, config: dict) -> str:
    """Tenta cada provedor em ordem e devolve o texto da resposta."""
    ai_cfg = config.get("ai", {})
    providers = ai_cfg.get("providers", [])
    timeout = ai_cfg.get("timeout_seconds", 30)

    if not providers:
        raise SemProvedorError("Nenhum provedor configurado em config.ai.providers")

    erros = []
    for p in providers:
        nome = p.get("name", "?")
        if nome in _esgotados:
            continue  # ja estourou cota nesta execucao, pula direto

        chave = os.environ.get(p.get("api_key_env", ""), "")
        if not chave:
            print(f"[IA] {nome}: chave ausente ({p.get('api_key_env')}) -> pulando")
            erros.append(f"{nome}: chave ausente")
            continue

        try:
            client = OpenAI(
                api_key=chave,
                base_url=p["base_url"],
                timeout=timeout,
                max_retries=0,  # sem retries: falhou, vai pro proximo na hora
            )
            resp = client.chat.completions.create(
                model=p["model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            texto = resp.choices[0].message.content or ""
            print(f"[IA] {nome} OK")
            return texto
        except Exception as exc:
            if _eh_erro_de_cota(exc):
                _esgotados.add(nome)
                print(f"[IA] {nome} sem cota (429) -> pulando pelo resto da execucao")
            else:
                print(f"[IA] {nome} falhou: {str(exc)[:160]}")
            erros.append(f"{nome}: {str(exc)[:160]}")

    raise SemProvedorError("Todos os provedores falharam: " + " | ".join(erros))


def chat_json(system_prompt: str, user_prompt: str, config: dict) -> dict:
    """Igual ao chat(), mas ja devolve o JSON parseado (uso do analyzer)."""
    return _extrair_json(chat(system_prompt, user_prompt, config))
