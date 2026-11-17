"""Roteador de IA com failover: Gemini -> Gemini3 -> Groq -> (heurística no analyzer).

Politica de novas tentativas:
- Cota esgotada (429) ou modelo morto (404): NAO repete -> pula pro próximo provedor.
- Erro passageiro (rede, 5xx, timeout): 1 nova tentativa apos 3s antes de trocar.
- Todos falharam: o analyzer cai na heuristica local (que nunca falha).
"""

import json
import os
import re
import time

from openai import OpenAI

_esgotados = set()
PAUSA_RETRY_SEGUNDOS = 3


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


def _eh_erro_de_modelo(exc) -> bool:
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None)
    return status == 404 or "does not exist" in msg or "not found" in msg


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


def _chamar_provedor(p: dict, system_prompt: str, user_prompt: str, timeout: int) -> str:
    client = OpenAI(
        api_key=os.environ.get(p.get("api_key_env", ""), ""),
        base_url=p["base_url"],
        timeout=timeout,
        max_retries=0,  # quem cuida das tentativas somos nós, não o SDK
    )
    resp = client.chat.completions.create(
        model=p["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""


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
            continue  # já falhou por cota/modelo nesta execução, pula direto

        if not os.environ.get(p.get("api_key_env", ""), ""):
            print(f"[IA] {nome}: chave ausente ({p.get('api_key_env')}) -> pulando")
            erros.append(f"{nome}: chave ausente")
            continue

        for tentativa in (1, 2):
            try:
                texto = _chamar_provedor(p, system_prompt, user_prompt, timeout)
                print(f"[IA] {nome} OK")
                return texto
            except Exception as exc:
                if _eh_erro_de_cota(exc):
                    _esgotados.add(nome)
                    print(f"[IA] {nome} sem cota (429) -> pulando pelo resto da execução")
                    erros.append(f"{nome}: cota esgotada")
                    break
                if _eh_erro_de_modelo(exc):
                    _esgotados.add(nome)
                    print(f"[IA] {nome} modelo indisponível (404) -> pulando pelo resto da execução")
                    erros.append(f"{nome}: modelo indisponível")
                    break
                if tentativa == 1:
                    print(f"[IA] {nome} falhou ({str(exc)[:80]}); "
                          f"nova tentativa em {PAUSA_RETRY_SEGUNDOS}s...")
                    time.sleep(PAUSA_RETRY_SEGUNDOS)
                    continue
                print(f"[IA] {nome} falhou de novo: {str(exc)[:160]}")
                erros.append(f"{nome}: {str(exc)[:160]}")

    raise SemProvedorError("Todos os provedores falharam: " + " | ".join(erros))


def chat_json(system_prompt: str, user_prompt: str, config: dict) -> dict:
    """Igual ao chat(), mas já devolve o JSON parseado (uso do analyzer)."""
    return _extrair_json(chat(system_prompt, user_prompt, config))
