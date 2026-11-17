"""Roteador de IA com failover: Gemini -> Gemini3 -> Groq -> (heurística no analyzer).

Politica de novas tentativas:
- Modelo morto (404): pula o provedor na hora.
- Cota DIARIA esgotada (429 'per day'): pula o provedor pelo resto da execucao.
- Limite por MINUTO (429 comum): aguarda 65s (a janela reinicia) e tenta 1 vez.
- Erro passageiro (rede, 5xx, timeout): 1 nova tentativa apos 3s.
- Todos falharam: o analyzer cai na heuristica local (que nunca falha).
"""

import json
import os
import re
import time

from openai import OpenAI

_esgotados = set()
PAUSA_RETRY_SEGUNDOS = 3
PAUSA_JANELA_SEGUNDOS = 65


class SemProvedorError(Exception):
    """Todos os provedores de IA falharam (o analyzer deve cair na heurística)."""


def _msg(exc) -> str:
    return str(exc).lower()


def _eh_429(exc) -> bool:
    return (
        getattr(exc, "status_code", None) == 429
        or "429" in _msg(exc)
        or "rate limit" in _msg(exc)
        or "resource_exhausted" in _msg(exc)
    )


def _eh_cota_diaria(exc) -> bool:
    return _eh_429(exc) and ("per day" in _msg(exc) or "daily" in _msg(exc))


def _eh_erro_de_modelo(exc) -> bool:
    return (
        getattr(exc, "status_code", None) == 404
        or "does not exist" in _msg(exc)
        or "not found" in _msg(exc)
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
            continue

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
                if _eh_erro_de_modelo(exc):
                    _esgotados.add(nome)
                    print(f"[IA] {nome} modelo indisponível (404) -> pulando provedor")
                    erros.append(f"{nome}: modelo indisponível")
                    break
                if _eh_cota_diaria(exc):
                    _esgotados.add(nome)
                    print(f"[IA] {nome} cota DIÁRIA esgotada -> pulando provedor")
                    erros.append(f"{nome}: cota diária")
                    break
                if _eh_429(exc):
                    if tentativa == 1:
                        print(f"[IA] {nome}: limite por minuto (429); "
                              f"aguardando {PAUSA_JANELA_SEGUNDOS}s p/ janela reiniciar...")
                        time.sleep(PAUSA_JANELA_SEGUNDOS)
                        continue
                    _esgotados.add(nome)
                    print(f"[IA] {nome} ainda sem vaga por minuto -> pulando provedor")
                    erros.append(f"{nome}: limite por minuto")
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
