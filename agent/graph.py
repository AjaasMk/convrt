"""
LangGraph stateful conversation graph.

Flow:
  START → agent → (tool_calls?) → tools → agent → … → END
"""
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

from .state import ConversationState
from .nodes import build_agent_node
from .tools import get_tools

_compiled_graph = None


def get_graph():
    """Return (and cache) the compiled LangGraph application."""
    global _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph

    tools = get_tools()
    agent_node = build_agent_node()

    workflow = StateGraph(ConversationState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools))

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", tools_condition)
    workflow.add_edge("tools", "agent")

    _compiled_graph = workflow.compile(checkpointer=MemorySaver())
    return _compiled_graph


def chat(message: str, session_id: str, customer_phone: str = "unknown",
         image_bytes: bytes = None, image_mime: str = "image/jpeg") -> str:
    """
    Send one user message (optionally with an uploaded product image) and
    return the agent's text reply. State is persisted per session_id.

    If image_bytes is given, a vision model first describes the product in the
    image (e.g. a reel screenshot), and that description is handed to the agent
    so it can match it to the SpiceNutrition catalogue.
    """
    from langchain_core.messages import HumanMessage
    from .rate_limiter import check_rate_limit
    from . import handoff

    message = message or ""

    # Anti-spam / cost guard — runs BEFORE any LLM call.
    allowed, canned = check_rate_limit(customer_phone)
    if not allowed:
        return canned

    # What the customer sees in the transcript vs. what the agent receives.
    display_message = message
    if image_bytes:
        display_message = "📷 [sent a product photo]" + (f" — {message}" if message else "")

    # Track the conversation + log the inbound customer message.
    handoff.ensure_conversation(session_id, customer_phone)
    handoff.log_message(session_id, "customer", display_message)

    # Human handoff: if a staff member has taken over, the AI stays silent.
    if handoff.get_mode(session_id) == "human":
        return ""  # staff handles this conversation

    # Vision step: turn the image into a description for the text agent.
    agent_message = message
    if image_bytes:
        from .vision import describe_product_image
        desc = describe_product_image(image_bytes, image_mime, caption=message)
        if desc.startswith("__VISION_ERROR__"):
            agent_message = (
                (message or "") +
                "\n[The customer sent a product photo but it couldn't be read. "
                "Politely ask them to describe the product or send a clearer photo.]"
            )
        else:
            agent_message = (
                f"The customer sent a product photo (likely a screenshot from a reel). "
                f"A vision system describes it as: \"{desc}\". "
                f"Use your tools to find the closest matching SpiceNutrition product(s) and give "
                f"details (price, flavours, availability). If we don't carry that exact brand, "
                f"recommend our closest equivalent and say so. "
                f"Customer's note: {message or '(none)'}"
            )

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}

    state_update = {
        "messages": [HumanMessage(content=agent_message)],
        "session_id": session_id,
        "customer_phone": customer_phone,
        "escalated": False,
    }

    result = graph.invoke(state_update, config=config)

    # If the agent escalated to a human this turn, flag for staff attention.
    if _escalated_this_turn(result["messages"]):
        handoff.mark_needs_attention(session_id, True)

    last = result["messages"][-1]
    reply = _content_to_text(getattr(last, "content", last))

    # The model often summarises away the payment QR/link. If request_payment ran
    # this turn, make sure its full output (QR image + UPI link) reaches the customer.
    pay_out = _tool_output(result["messages"], "request_payment")
    if pay_out and "/api/payment/qr" not in reply:
        reply = (reply.rstrip() + "\n\n" + pay_out).strip() if reply.strip() else pay_out

    handoff.log_message(session_id, "ai", reply)
    return reply


def _tool_output(messages, tool_name: str) -> str:
    """Return the most recent ToolMessage content for the given tool name."""
    for m in reversed(messages):
        if getattr(m, "name", None) == tool_name and getattr(m, "type", "") == "tool":
            return _content_to_text(getattr(m, "content", ""))
    return ""


def _escalated_this_turn(messages) -> bool:
    """Detect if the agent called escalate_to_human in this turn."""
    for m in messages:
        calls = getattr(m, "tool_calls", None) or []
        for c in calls:
            name = c.get("name") if isinstance(c, dict) else getattr(c, "name", "")
            if name == "escalate_to_human":
                return True
    return False


def _content_to_text(content) -> str:
    """
    Normalise message content to plain text.
    Some models (e.g. Gemini 'thinking' models) return content as a list of
    blocks like [{'type':'text','text':...}] instead of a plain string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    parts.append(block["text"])
                elif "text" in block and isinstance(block["text"], str):
                    parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        if parts:
            return "\n".join(parts).strip()
    return str(content)
