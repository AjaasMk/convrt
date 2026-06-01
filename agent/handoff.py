"""
Human handoff (live agent takeover) logic.

Rules:
  - Staff starts typing in a conversation  -> mode='human', AI stops auto-replying.
  - AI gets stuck / escalates              -> needs_attention=1, staff is notified.
  - Staff inactive for TIMEOUT seconds      -> AI resumes automatically (mode='ai').
  - Staff clicks "Resume AI"                -> mode='ai' immediately.

State lives in the `conversations` and `messages` tables (shared across UI tabs).
"""
import os
from datetime import datetime, timedelta

from database.models import get_connection, row_to_dict, rows_to_list

# Seconds of staff inactivity after which the AI auto-resumes.
HANDOFF_TIMEOUT = int(os.getenv("HANDOFF_TIMEOUT_SECONDS", "120"))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_conversation(session_id: str, phone: str = "") -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM conversations WHERE session_id=?", (session_id,)
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO conversations (session_id, customer_phone, mode) VALUES (?,?,'ai')",
            (session_id, phone),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM conversations WHERE session_id=?", (session_id,)
        ).fetchone()
    elif phone and not row["customer_phone"]:
        conn.execute(
            "UPDATE conversations SET customer_phone=? WHERE session_id=?",
            (phone, session_id),
        )
        conn.commit()
    result = row_to_dict(row)
    conn.close()
    return result


def log_message(session_id: str, role: str, content: str) -> None:
    """role: 'customer' | 'ai' | 'staff'"""
    if not content:
        return
    conn = get_connection()
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?,?,?)",
        (session_id, role, content),
    )
    conn.execute(
        "UPDATE conversations SET updated_at=? WHERE session_id=?",
        (_now(), session_id),
    )
    conn.commit()
    conn.close()


def get_messages(session_id: str) -> list[dict]:
    conn = get_connection()
    rows = rows_to_list(conn.execute(
        "SELECT role, content, created_at FROM messages WHERE session_id=? ORDER BY id",
        (session_id,),
    ).fetchall())
    conn.close()
    return rows


def maybe_auto_resume(session_id: str) -> bool:
    """
    If the conversation is in human mode but staff have been inactive past the
    timeout, flip back to AI. Returns True if a resume happened.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT mode, last_human_activity FROM conversations WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if not row or row["mode"] != "human":
        conn.close()
        return False

    last = row["last_human_activity"]
    resumed = False
    if last:
        try:
            last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_dt > timedelta(seconds=HANDOFF_TIMEOUT):
                conn.execute(
                    "UPDATE conversations SET mode='ai', updated_at=? WHERE session_id=?",
                    (_now(), session_id),
                )
                conn.commit()
                resumed = True
        except ValueError:
            pass
    conn.close()
    return resumed


def get_mode(session_id: str) -> str:
    """Returns 'ai' or 'human', applying auto-resume first."""
    maybe_auto_resume(session_id)
    conn = get_connection()
    row = conn.execute(
        "SELECT mode FROM conversations WHERE session_id=?", (session_id,)
    ).fetchone()
    conn.close()
    return row["mode"] if row else "ai"


def staff_start_typing(session_id: str) -> None:
    """Staff focused/started typing -> take over, pause AI immediately."""
    ensure_conversation(session_id)
    conn = get_connection()
    conn.execute(
        "UPDATE conversations SET mode='human', last_human_activity=?, updated_at=? WHERE session_id=?",
        (_now(), _now(), session_id),
    )
    conn.commit()
    conn.close()


def staff_send(session_id: str, content: str) -> None:
    """Staff sends a manual reply; keeps the chat in human mode."""
    ensure_conversation(session_id)
    conn = get_connection()
    conn.execute(
        "UPDATE conversations SET mode='human', needs_attention=0, last_human_activity=?, updated_at=? WHERE session_id=?",
        (_now(), _now(), session_id),
    )
    conn.commit()
    conn.close()
    log_message(session_id, "staff", content)


def resume_ai(session_id: str) -> None:
    """Manual 'Resume AI' button."""
    conn = get_connection()
    conn.execute(
        "UPDATE conversations SET mode='ai', needs_attention=0, updated_at=? WHERE session_id=?",
        (_now(), session_id),
    )
    conn.commit()
    conn.close()


def mark_needs_attention(session_id: str, on: bool = True) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE conversations SET needs_attention=?, updated_at=? WHERE session_id=?",
        (1 if on else 0, _now(), session_id),
    )
    conn.commit()
    conn.close()


def list_conversations() -> list[dict]:
    """For the staff dashboard live panel."""
    conn = get_connection()
    rows = rows_to_list(conn.execute(
        """
        SELECT c.session_id, c.customer_phone, c.mode, c.needs_attention, c.updated_at,
               (SELECT content FROM messages m WHERE m.session_id=c.session_id ORDER BY m.id DESC LIMIT 1) AS last_message,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id=c.session_id) AS msg_count
        FROM conversations c
        ORDER BY c.needs_attention DESC, c.updated_at DESC
        """
    ).fetchall())
    conn.close()
    return rows
