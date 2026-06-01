"""
Lightweight in-memory rate limiter (sliding window) keyed by customer phone.

Protects against spam / runaway token costs BEFORE the LLM is ever called.
For production, swap the in-memory store for Redis (same interface).

Limits (configurable):
  - PER_MINUTE : soft cap → canned "catching up" reply, no LLM call
  - PER_DAY    : hard cap → stop auto-replying, flag for review
"""
import os
import time
from collections import defaultdict, deque
from threading import Lock

PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
PER_DAY = int(os.getenv("RATE_LIMIT_PER_DAY", "200"))

_MINUTE = 60
_DAY = 24 * 60 * 60

# phone -> deque[timestamps]
_events: dict[str, deque] = defaultdict(deque)
_lock = Lock()

CANNED_MINUTE = (
    "🙏 You're sending messages a bit fast — give me a few seconds to catch up "
    "and I'll get right back to you!"
)
CANNED_DAY = (
    "🙏 You've reached the daily message limit for this chat. Our team has been "
    "notified and will follow up with you soon. Thanks for your patience!"
)


def check_rate_limit(phone: str) -> tuple[bool, str]:
    """
    Record an incoming message and decide whether to allow it.

    Returns (allowed, canned_reply):
      allowed = True  -> proceed to the agent (LLM call)
      allowed = False -> send canned_reply instead (no LLM call, no cost)
    """
    if not phone or phone == "unknown":
        return True, ""

    now = time.time()
    with _lock:
        dq = _events[phone]
        # drop events older than a day
        while dq and now - dq[0] > _DAY:
            dq.popleft()

        in_last_minute = sum(1 for t in dq if now - t <= _MINUTE)
        in_last_day = len(dq)

        # Always record this attempt (so spammers keep tripping the limit)
        dq.append(now)

        if in_last_day >= PER_DAY:
            return False, CANNED_DAY
        if in_last_minute >= PER_MINUTE:
            return False, CANNED_MINUTE

    return True, ""


def reset(phone: str | None = None) -> None:
    """Clear counters (testing / admin use)."""
    with _lock:
        if phone is None:
            _events.clear()
        else:
            _events.pop(phone, None)
