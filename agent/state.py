from typing import Annotated, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class ConversationState(TypedDict):
    messages:        Annotated[list, add_messages]
    customer_phone:  Optional[str]
    customer_name:   Optional[str]
    customer_id:     Optional[int]
    session_id:      str
    escalated:       bool
