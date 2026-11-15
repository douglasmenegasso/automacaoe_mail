"""Classificação e análise de e-mails usando LLM (OpenAI).

Categorias:
- spam_propaganda : propaganda, newsletters, promoções, spam -> apagar/arquivar
- responde_se      : dá para responder automaticamente (confirmação, agradecimento, FAQ simples)
- precisa_humano   : exige decisão/informação do dono da caixa -> avisar por WhatsApp
"""
import json
import os
import re

from openai import OpenAI

SYSTEM_PROMPT = """Você é um assistente que analisa e-mails em nome do usuário.
Responda SEMPRE apenas com JSON válido, no formato:
{
  "categoria": "spam_propaganda" | "responde_se" | "precisa_humano",
  "motivo": "explicação curta em português",
  "resposta": "texto da resposta automática se categoria for responde_se, senão null",
  "resumo_para_whatsapp": "se precisa_humano: resumo curto do e-mail + o que o usuário precisa fazer/saber. senão null"
}

Regras:
- Propaganda, promoções, newsletters, spam, notificações de redes sociais sem ação => spam_propaganda
- Pedidos simples que não exigem informação pessoal (confirmar recebimento, agradecer, agendar algo já proposto com data livre?) NÃO responda sozinho se depender de agenda/dados do usuário => precisa_humano
- Respostas automáticas devem ser educadas, curtas e genéricas, nunca inventar dados (datas, valores, endereços).
- Se houver dúvida sobre segurança ou conteúdo suspeito/pishing => precisa_humano."""


def _get_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("[ERRO] Defina a variável de ambiente OPENAI_API_KEY.")
    return OpenAI(api_key=api_key)


def classify_email(email: dict, model: str = "gpt-4o-mini") -> dict:
    """Retorna dict com categoria, motivo, resposta e resumo para WhatsApp."""
    user_prompt = (
        f"DE: {email['from']}\n"
        f"ASSUNTO: {email['subject']}\n"
        f"DATA: {email['date']}\n"
        f"CORPO:\n{email['body'] or email['snippet']}"
    )
    try:
        resp = _get_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
    except Exception as exc:  # noqa: BLE001
        print(f"[AVISO] Falha na análise por IA ({exc}); usando heurística local.")
        result = _heuristic_classify(email)

    # Normaliza campos
    result.setdefault("categoria", "precisa_humano")
    result.setdefault("motivo", "")
    result.setdefault("resposta", None)
    result.setdefault("resumo_para_whatsapp", None)
    if result["categoria"] not in ("spam_propaganda", "responde_se", "precisa_humano"):
        result["categoria"] = "precisa_humano"
    return result


# ----------------- Fallback sem IA (heurística simples) -----------------
_SPAM_PATTERNS = re.compile(
    r"(unsubscribe|descadastre|promo[cç][aã]o|desconto|oferta|frete gr[aã]tis|"
    r"black friday|newsletter|cupom|% off|compre agora|aproveite j[aá])",
    re.IGNORECASE,
)


def _heuristic_classify(email: dict) -> dict:
    text = f"{email['subject']} {email['body']} {email['snippet']}"
    if _SPAM_PATTERNS.search(text):
        return {
            "categoria": "spam_propaganda",
            "motivo": "Heurística: palavras típicas de propaganda/spam.",
            "resposta": None,
            "resumo_para_whatsapp": None,
        }
    return {
        "categoria": "precisa_humano",
        "motivo": "Heurística: sem IA disponível, melhor avisar o usuário.",
        "resposta": None,
        "resumo_para_whatsapp": f"E-mail de {email['from']} - Assunto: {email['subject']}",
    }
