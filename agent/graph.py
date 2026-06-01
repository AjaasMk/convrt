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


def chat(message: str, session_id: str, customer_phone: str = "unknown") -> str:
    """
    Send one user message and return the agent's text reply.
    State is persisted per session_id via MemorySaver.
    """
    from langchain_core.messages import HumanMessage
    from .rate_limiter import check_rate_limit
    from . import handoff

    # Anti-spam / cost guard — runs BEFORE any LLM call.
    allowed, canned = check_rate_limit(customer_phone)
    if not allowed:
        return canned

    # Track the conversation + log the inbound customer message.
    handoff.ensure_conversation(session_id, customer_phone)
    handoff.log_message(session_id, "customer", message)

    # Human handoff: if a staff member has taken over (or is typing),
    # the AI stays silent. AI auto-resumes after the inactivity timeout.
    if handoff.get_mode(session_id) == "human":
        return ""  # no AI reply; staff handles this conversation

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}

    state_update = {
        "messages": [HumanMessage(content=message)],
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
    handoff.log_message(session_id, "ai", reply)
    return reply


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
