"""
FastAPI backend + web UI for Convrt.
Serves a custom HTML/Tailwind single-page app (no Gradio) and JSON APIs for
the customer chat, staff dashboard, inventory, and human handoff.

Start:  uvicorn api.main:app --host 0.0.0.0 --port 7860
"""
import os
import base64
import uuid
import secrets
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent / ".env")

from database.models import init_db, get_connection, rows_to_list, row_to_dict
from database.seed_data import seed_all
from agent.graph import chat
from agent import handoff

FRONTEND = Path(__file__).parent.parent / "frontend" / "index.html"

APP_USERNAME = os.getenv("APP_USERNAME")
APP_PASSWORD = os.getenv("APP_PASSWORD")
AUTH_ENABLED = bool(APP_USERNAME and APP_PASSWORD)
_SESSIONS: set[str] = set()

app = FastAPI(title="Convrt – WhatsApp AI Sales Agent", version="2.0.0")


@app.on_event("startup")
def startup():
    seed_all()


# ── Auth ──────────────────────────────────────────────────────────────────────

def _is_authed(request: Request) -> bool:
    if not AUTH_ENABLED:
        return True
    tok = request.cookies.get("convrt_session")
    return bool(tok) and tok in _SESSIONS


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if path in ("/login", "/health") or path.startswith("/static"):
        return await call_next(request)
    if path == "/" or path.startswith("/api"):
        if not _is_authed(request):
            if path == "/":
                return RedirectResponse("/login")
            return JSONResponse({"detail": "authentication required"}, status_code=401)
    return await call_next(request)


def _login_page(error: str = "") -> str:
    err = f'<p style="color:#ef4444;margin-top:8px">{error}</p>' if error else ""
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>Convrt – Login</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center font-sans">
<form method="post" action="/login" class="bg-slate-900 p-8 rounded-2xl shadow-xl w-80 border border-slate-800">
  <h1 class="text-xl font-bold mb-1">💪 Convrt</h1>
  <p class="text-slate-400 text-sm mb-6">Staff Login</p>
  <input name="username" placeholder="Username" class="w-full mb-3 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 outline-none focus:border-blue-500">
  <input name="password" type="password" placeholder="Password" class="w-full mb-4 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 outline-none focus:border-blue-500">
  <button class="w-full bg-blue-600 hover:bg-blue-500 py-2 rounded-lg font-semibold">Login</button>
  {err}
</form></body></html>"""


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return _login_page()


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    if username == APP_USERNAME and password == APP_PASSWORD:
        tok = secrets.token_urlsafe(24)
        _SESSIONS.add(tok)
        resp = RedirectResponse("/", status_code=303)
        # SameSite=None + Secure so the cookie works inside HF's cross-site iframe.
        resp.set_cookie("convrt_session", tok, httponly=True, samesite="none", secure=True)
        return resp
    return HTMLResponse(_login_page("Invalid username or password."), status_code=401)


@app.get("/logout")
def logout(request: Request):
    tok = request.cookies.get("convrt_session")
    _SESSIONS.discard(tok)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("convrt_session")
    return resp


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Frontend ────────────────────────────────────────────────────────────────--

@app.get("/", response_class=HTMLResponse)
def index():
    if FRONTEND.exists():
        return FileResponse(str(FRONTEND))
    return HTMLResponse("<h1>Convrt</h1><p>Frontend not found.</p>")


# ── Customer chat ──────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: Optional[str] = ""
    session_id: Optional[str] = None
    customer_phone: Optional[str] = "unknown"
    image_b64: Optional[str] = None      # base64 (optionally with data: prefix)
    image_mime: Optional[str] = "image/jpeg"


def _transcript(session_id: str) -> list:
    return handoff.get_messages(session_id)


@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    image_bytes = None
    if req.image_b64:
        try:
            data = req.image_b64.split(",", 1)[-1]  # strip data: prefix if present
            image_bytes = base64.b64decode(data)
        except Exception:
            image_bytes = None
    try:
        reply = chat(req.message or "", session_id, req.customer_phone or "unknown",
                     image_bytes=image_bytes, image_mime=req.image_mime or "image/jpeg")
    except Exception as e:
        reply = f"⚠️ Agent error: {e}"
        handoff.log_message(session_id, "ai", reply)
    return {"reply": reply, "session_id": session_id, "messages": _transcript(session_id)}


@app.get("/api/chat/{session_id}/messages")
def chat_messages(session_id: str):
    """Poll for new messages (e.g. staff replies during a human takeover)."""
    return {"messages": _transcript(session_id), "mode": handoff.get_mode(session_id)}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def dashboard_stats():
    conn = get_connection()
    g = lambda q: conn.execute(q).fetchone()[0]
    data = {
        "today_orders":   g("SELECT COUNT(*) FROM orders WHERE DATE(created_at)=DATE('now')"),
        "today_revenue":  round(g("SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE DATE(created_at)=DATE('now') AND status!='cancelled'"), 2),
        "total_orders":   g("SELECT COUNT(*) FROM orders"),
        "total_revenue":  round(g("SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE status!='cancelled'"), 2),
        "pending_orders": g("SELECT COUNT(*) FROM orders WHERE status='pending'"),
        "pending_returns": g("SELECT COUNT(*) FROM returns WHERE status='requested'"),
        "open_escalations": g("SELECT COUNT(*) FROM escalations WHERE status='pending'"),
        "low_stock": g("SELECT COUNT(*) FROM product_variants WHERE stock>0 AND stock<=5"),
    }
    conn.close()
    return data


# ── Orders ────────────────────────────────────────────────────────────────────

@app.get("/api/orders")
def list_orders(limit: int = 50):
    conn = get_connection()
    rows = rows_to_list(conn.execute(
        """
        SELECT o.id, c.name as customer, c.phone,
               o.status, printf('₹%.0f', o.total_amount) as amount, o.created_at
        FROM orders o JOIN customers c ON c.id=o.customer_id
        ORDER BY o.created_at DESC LIMIT ?
        """, (limit,)).fetchall())
    conn.close()
    return rows


class OrderStatusUpdate(BaseModel):
    status: str


@app.patch("/api/orders/{order_id}/status")
def update_order_status(order_id: str, body: OrderStatusUpdate):
    valid = {"pending", "processing", "shipped", "delivered", "cancelled"}
    if body.status not in valid:
        raise HTTPException(400, f"status must be one of {valid}")
    conn = get_connection()
    conn.execute("UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                 (body.status, order_id.upper()))
    conn.commit()
    conn.close()
    return {"order_id": order_id.upper(), "status": body.status}


# ── Inventory ─────────────────────────────────────────────────────────────────

@app.get("/api/inventory")
def list_inventory(low_stock: bool = False):
    conn = get_connection()
    q = """
        SELECT v.id as variant_id, p.name, p.category, v.size, v.flavor,
               printf('₹%.0f', v.price) as price, v.stock
        FROM products p JOIN product_variants v ON p.id=v.product_id
    """
    if low_stock:
        q += " WHERE v.stock <= 5"
    q += " ORDER BY p.name, v.size, v.flavor"
    rows = rows_to_list(conn.execute(q).fetchall())
    conn.close()
    return rows


class StockUpdate(BaseModel):
    variant_id: int
    stock: int


@app.put("/api/inventory/stock")
def update_stock(body: StockUpdate):
    if body.stock < 0:
        raise HTTPException(400, "stock cannot be negative")
    conn = get_connection()
    conn.execute("UPDATE product_variants SET stock=? WHERE id=?", (body.stock, body.variant_id))
    conn.commit()
    conn.close()
    return {"variant_id": body.variant_id, "stock": body.stock}


# ── Escalations ─────────────────────────────────────────────────────────────--

@app.get("/api/escalations")
def list_escalations():
    conn = get_connection()
    rows = rows_to_list(conn.execute(
        "SELECT id, customer_phone, issue, status, created_at FROM escalations ORDER BY created_at DESC LIMIT 50"
    ).fetchall())
    conn.close()
    return rows


@app.patch("/api/escalations/{escalation_id}/resolve")
def resolve_escalation(escalation_id: int):
    conn = get_connection()
    conn.execute("UPDATE escalations SET status='resolved' WHERE id=?", (escalation_id,))
    conn.commit()
    conn.close()
    return {"escalation_id": escalation_id, "status": "resolved"}


# ── Human handoff ───────────────────────────────────────────────────────────--

@app.get("/api/conversations")
def conversations():
    return handoff.list_conversations()


@app.get("/api/conversation/{session_id}")
def conversation(session_id: str):
    handoff.maybe_auto_resume(session_id)
    return {"messages": handoff.get_messages(session_id), "mode": handoff.get_mode(session_id)}


class SessionBody(BaseModel):
    session_id: str


class ReplyBody(BaseModel):
    session_id: str
    text: str


@app.post("/api/handoff/typing")
def handoff_typing(body: SessionBody):
    handoff.staff_start_typing(body.session_id)
    return {"mode": "human"}


@app.post("/api/handoff/reply")
def handoff_reply(body: ReplyBody):
    if not body.text.strip():
        raise HTTPException(400, "empty reply")
    handoff.staff_send(body.session_id, body.text.strip())
    return {"messages": handoff.get_messages(body.session_id), "mode": "human"}


@app.post("/api/handoff/resume")
def handoff_resume(body: SessionBody):
    handoff.resume_ai(body.session_id)
    return {"mode": "ai"}


# ── Payment QR ────────────────────────────────────────────────────────────────

@app.get("/api/payment/qr")
def payment_qr(order: Optional[str] = None, amount: Optional[float] = None):
    import io as _io
    import yaml as _yaml
    from urllib.parse import quote
    import qrcode

    cfgp = Path(__file__).parent.parent / "config.yaml"
    cfg = _yaml.safe_load(cfgp.read_text(encoding="utf-8")) if cfgp.exists() else {}
    upi = cfg.get("upi_id", "spicenutrition@upi")
    payee = cfg.get("payee_name", "SpiceNutrition")

    amt = amount
    if order:
        conn = get_connection()
        row = conn.execute("SELECT total_amount FROM orders WHERE id=?", (order.upper(),)).fetchone()
        conn.close()
        if row:
            amt = row[0]
    amt = amt or 0

    uri = f"upi://pay?pa={upi}&pn={quote(payee)}&am={amt:.0f}&cu=INR"
    if order:
        uri += f"&tn=Order%20{order.upper()}"

    img = qrcode.make(uri)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")
