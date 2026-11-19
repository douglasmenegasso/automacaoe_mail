"""Classificação e análise de e-mails usando LLM com failover (Gemini -> Groq).

Categorias:
- spam_propaganda : propaganda, newsletters, promoções, spam -> apagar/arquivar
- responde_se      : dá para responder automaticamente (confirmação, agradecimento, FAQ simples)
- precisa_humano   : exige decisão/informação do dono da caixa -> avisar por WhatsApp

A chamada de IA passa pelo ai_router (Gemini -> Groq). Se todos os provedores
falharem, usa a heurística local (sem IA) como último recurso.
"""
import re

from ai_router import chat_json

SYSTEM_PROMPT = """Você é um assistente que analisa e-mails em nome do usuário.
Responda SEMPRE apenas com JSON válido, no formato:
{
  "categoria": "spam_propaganda" | "responde_se" | "precisa_humano",
  "motivo": "explicação curta em português",
  "resposta": "texto da resposta automática se categoria for responde_se, senão null",
  "resumo_para_whatsapp": "se precisa_humano: resumo curto do e-mail + o que o usuário precisa fazer/saber. senão null",
  "pasta_sugerida": "se precisa_humano: escolha EXATAMENTE uma destas palavras: Financeiro, Bancos, Seguranca, Vagas, Pessoal, Contas, Fornecedores, Trabalho, Outros. Se nenhuma couber bem, use Outros. senão null"
}

Regras:
- Propaganda, promoções, newsletters, spam, notificações de redes sociais sem ação => spam_propaganda
- Pedidos simples que não exigem informação pessoal (confirmar recebimento, agradecer, agendar algo já proposto com data livre?) NÃO responda sozinho se depender de agenda/dados do usuário => precisa_humano
- Respostas automáticas devem ser educadas, curtas e genéricas, nunca inventar dados (datas, valores, endereços).
- Se houver dúvida sobre segurança ou conteúdo suspeito/pishing => precisa_humano.
- Quando categoria for precisa_humano, SEMPRE preencha pasta_sugerida com uma das palavras da lista (sem acentos, sem espaços). Quando categoria for spam_propaganda ou responde_se, pasta_sugerida deve ser null."""


def classify_email(email: dict, config=None, **_legado) -> dict:
    """Retorna dict com categoria, motivo, resposta, resumo para WhatsApp e pasta.

    config: dict completo do config.json (o roteador usa o bloco "ai").
    **_legado: engole argumentos do formato antigo (ex.: model="gpt-4o-mini")
    para nao quebrar enquanto o main.py nao for atualizado.
    """
    if not isinstance(config, dict):
        config = {}

    user_prompt = (
        f"DE: {email['from']}\n"
        f"ASSUNTO: {email['subject']}\n"
        f"DATA: {email['date']}\n"
        f"CORPO:\n{email['body'] or email['snippet']}"
    )
    try:
        result = chat_json(SYSTEM_PROMPT, user_prompt, config)
    except Exception as exc:  # noqa: BLE001
        print(f"[AVISO] Falha na análise por IA ({exc}); usando heurística local.")
        result = _heuristic_classify(email)

    # Normaliza campos
    result.setdefault("categoria", "precisa_humano")
    result.setdefault("motivo", "")
    result.setdefault("resposta", None)
    result.setdefault("resumo_para_whatsapp", None)
    result.setdefault("pasta_sugerida", None)
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
            "pasta_sugerida": None,
        }
    return {
        "categoria": "precisa_humano",
        "motivo": "Heurística: sem IA disponível, melhor avisar o usuário.",
        "resposta": None,
        "resumo_para_whatsapp": f"E-mail de {email['from']} - Assunto: {email['subject']}",
        "pasta_sugerida": None,
    }
