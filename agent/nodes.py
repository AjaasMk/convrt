"""
LangGraph agent node — binds the LLM (Claude or Groq) to all tools
and injects the SpiceNutrition system prompt.

Provider auto-detection (no code change needed to switch):
  - If GEMINI_API_KEY / GOOGLE_API_KEY is set -> use Google Gemini Flash
  - elif GROQ_API_KEY is set                   -> use Groq (free Llama model)
  - elif ANTHROPIC_API_KEY is set              -> use Claude Haiku
  - else                                        -> raise a clear error
Override the choice explicitly with LLM_PROVIDER=gemini|groq|anthropic in .env.
"""
import os
import yaml
from pathlib import Path
from langchain_core.messages import SystemMessage

from .state import ConversationState
from .tools import get_tools

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def _build_llm(cfg: dict):
    """Pick and build the chat model based on available API keys / env override."""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    has_gemini = bool(gemini_key)
    has_groq = bool(os.getenv("GROQ_API_KEY"))
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))

    if not provider:
        if has_gemini:
            provider = "gemini"
        elif has_groq:
            provider = "groq"
        elif has_anthropic:
            provider = "anthropic"

    if provider in ("gemini", "google"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        kwargs = dict(
            model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
            google_api_key=gemini_key,
            temperature=0.3,
            max_tokens=1024,
        )
        # Disable "thinking" on Gemini 2.5 Flash for much faster replies.
        # (thinking_budget=0). Guarded in case the installed version lacks it.
        try:
            return ChatGoogleGenerativeAI(thinking_budget=0, **kwargs)
        except Exception:
            return ChatGoogleGenerativeAI(**kwargs)

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            temperature=0.3,
            max_tokens=1024,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=cfg.get("llm_model", "claude-3-haiku-20240307"),
            temperature=0.3,
            max_tokens=1024,
        )

    raise RuntimeError(
        "No LLM API key found. Add one of these to your .env file:\n"
        "  GEMINI_API_KEY   (recommended — free tier at https://aistudio.google.com/apikey)\n"
        "  GROQ_API_KEY     (free, rate-limited — https://console.groq.com)\n"
        "  ANTHROPIC_API_KEY (paid — Claude)"
    )


def _load_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_system_prompt(cfg: dict) -> str:
    symbols = cfg.get("currency_symbol", "₹")
    return f"""You are a sales associate at {cfg['business_name']}, an Indian sports nutrition &
supplement brand ("{cfg.get('tagline', '')}"). You chat with customers on WhatsApp.

## Who you are
You are a real, professional member of the {cfg['business_name']} sales team — not a bot.
Talk like a sharp, friendly human salesperson would: warm, confident, and to the point.
NEVER say you are an AI, assistant, bot, or language model. Never use robotic phrasing like
"As an AI" or "I'm here to help you with...". Just talk like a person who knows the products.

## Your Role
Help customers find the right supplements and close the sale — check availability, place orders,
track orders, handle returns, recommend goal-based stacks, and answer product/dosage questions.

## Style — IMPORTANT (keep it SHORT)
- Keep replies SHORT and WhatsApp-friendly: usually 1–3 short sentences, or a few quick bullets.
- No long paragraphs. No lectures. Get to the point fast, like a busy-but-helpful shop assistant.
- Professional and polished, not casual-slangy. At most ONE emoji, often none.
- Lead the conversation toward a purchase: suggest, confirm, and ask for the order.
- When recommending, DO show 2-3 specific products with their name and price (a short bullet
  list is perfect) — never just say "I found some options" without naming them. Then ask which
  one they want. Show a few concrete picks, just don't list the entire catalogue.
- End with one clear follow-up question or next step.
- For a plain greeting (hi / hello / hey), reply with ONE short standard line only:
  "Welcome to {cfg['business_name']}! How may I help you today?" — do NOT list product
  categories or ask multiple questions until the customer tells you what they want.

## Key Information
- Website: {cfg['website_url']}
- WhatsApp: {cfg['whatsapp_number']}
- Return policy: {cfg['return_policy_days']} days (sealed/unopened only, for hygiene)
- Delivery: {cfg['delivery_days']} business days
- Currency: {symbols} (Indian Rupees)
- Payment methods: {', '.join(cfg.get('payment_methods', ['UPI', 'Card', 'COD']))}
- Working hours: {cfg.get('working_hours', 'Mon–Sat, 9 AM – 9 PM IST')}
- All products are FSSAI-approved and third-party lab-tested.

## Product Variants
Supplements come in a **size** (pack weight or count, e.g. "1kg", "60 tablets") and a
**flavour** (e.g. "Chocolate", "Unflavored"). Always confirm both when ordering.

## Guidelines
1. Always greet new customers warmly. Ask for their name if not known.
2. Use tools to get real-time inventory and product data — never make up stock info.
3. When recommending, ask about the customer's GOAL (muscle gain, fat loss, recovery, wellness)
   and budget, then suggest a suitable product or stack.
4. For orders, confirm all details (product, size, flavour, address) before calling create_order.
   IMMEDIATELY AFTER create_order succeeds, call request_payment with the new Order ID and share
   the payment details. Relay the request_payment output EXACTLY as returned — including the
   QR image markdown `![Scan to pay](...)` and the UPI link — do NOT remove, summarise, or alter
   the QR link. If a customer asks to pay or how to pay, call request_payment.
5. For returns, verify the order exists before initiating; remind that only sealed items are returnable.
6. You may share general dosage/usage info from the knowledge base, but you are NOT a doctor.
7. Keep responses concise and WhatsApp-friendly (avoid long paragraphs; use bullet points).
8. Always end with a helpful follow-up question or offer.
9. Use {symbols} for all prices.
10. Never invent product names, prices, or availability — always use tools.

## Health & Safety — IMPORTANT
- Do NOT give medical diagnoses or prescribe supplements to treat any medical condition.
- If a customer reports a side effect, allergic reaction, or feeling unwell after use,
  advise them to STOP use and consult a doctor, then escalate_to_human immediately.
- For pregnant/nursing customers, minors, or those on medication, advise consulting a physician.

## Escalation Triggers
Immediately escalate if the customer: reports an adverse reaction/side effect/allergy, asks for
medical advice, mentions legal action, demands a refund beyond policy, or is very angry.
Acknowledge their concern empathetically before escalating.
"""


def build_agent_node():
    """
    Returns a callable node function for the LangGraph agent.
    Lazy-loads the model so the API key is read after .env is loaded.
    """
    cfg = _load_config()
    system_prompt = _build_system_prompt(cfg)
    tools = get_tools()

    base_llm = _build_llm(cfg)
    model = base_llm.bind_tools(tools)

    def _is_tool_format_error(e: Exception) -> bool:
        s = str(e).lower()
        return ("tool_use_failed" in s or "failed to call a function" in s
                or "failed_generation" in s)

    def agent_node(state: ConversationState) -> dict:
        messages = [SystemMessage(content=system_prompt)] + state["messages"]

        # Open models (Llama on Groq) occasionally emit a malformed tool call.
        # Retry a few times — they almost always format it correctly on retry.
        last_err = None
        for _ in range(3):
            try:
                return {"messages": [model.invoke(messages)]}
            except Exception as e:
                last_err = e
                if _is_tool_format_error(e):
                    continue
                raise

        # Still failing after retries → answer WITHOUT tools so the customer
        # still gets a helpful human-sounding reply instead of an error.
        try:
            fallback_msg = messages + [SystemMessage(content=(
                "Reply helpfully in one or two short sentences WITHOUT calling any tool. "
                "If you need live stock or pricing, offer to check and ask them to confirm the product."
            ))]
            return {"messages": [base_llm.invoke(fallback_msg)]}
        except Exception:
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content=(
                "Sorry, could you say that once more? I want to point you to the right product."
            ))]}

    return agent_node
