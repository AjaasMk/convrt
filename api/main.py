"""
FastAPI backend for Convrt.
Exposes endpoints for WhatsApp webhook integration, orders, inventory, and stats.

Start:  uvicorn api.main:app --reload --port 8000
"""
import os
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent / ".env")

from database.models import init_db, get_connection, rows_to_list, row_to_dict
from database.seed_data import seed_all
from agent.graph import chat

app = FastAPI(title="Convrt – WhatsApp AI Sales Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    seed_all()


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    customer_phone: Optional[str] = "unknown"


class ChatResponse(BaseModel):
    reply: str
    session_id: str


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    try:
        reply = chat(req.message, session_id, req.customer_phone or "unknown")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return ChatResponse(reply=reply, session_id=session_id)


# ── Orders ────────────────────────────────────────────────────────────────────

@app.get("/orders")
def list_orders(status: Optional[str] = None, limit: int = 50):
    conn = get_connection()
    q = """
        SELECT o.id, o.status, o.total_amount, o.created_at,
               c.name as customer_name, c.phone as customer_phone
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
    """
    params = []
    if status:
        q += " WHERE o.status = ?"
        params.append(status)
    q += " ORDER BY o.created_at DESC LIMIT ?"
    params.append(limit)
    rows = rows_to_list(conn.execute(q, params).fetchall())
    conn.close()
    return rows


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    conn = get_connection()
    order = row_to_dict(conn.execute(
        """
        SELECT o.*, c.name as customer_name, c.phone as customer_phone
        FROM orders o JOIN customers c ON c.id = o.customer_id
        WHERE o.id = ?
        """,
        (order_id.upper(),),
    ).fetchone())
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found")
    items = rows_to_list(conn.execute(
        """
        SELECT p.name, v.size, v.flavor, oi.quantity, oi.unit_price
        FROM order_items oi
        JOIN product_variants v ON v.id = oi.variant_id
        JOIN products p ON p.id = v.product_id
        WHERE oi.order_id = ?
        """,
        (order_id.upper(),),
    ).fetchall())
    conn.close()
    return {**order, "items": items}


class OrderStatusUpdate(BaseModel):
    status: str


@app.patch("/orders/{order_id}/status")
def update_order_status(order_id: str, body: OrderStatusUpdate):
    valid = {"pending", "processing", "shipped", "delivered", "cancelled"}
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {valid}")
    conn = get_connection()
    conn.execute(
        "UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (body.status, order_id.upper()),
    )
    conn.commit()
    conn.close()
    return {"order_id": order_id.upper(), "status": body.status}


# ── Inventory ─────────────────────────────────────────────────────────────────

@app.get("/inventory")
def list_inventory(low_stock: bool = False):
    conn = get_connection()
    q = """
        SELECT p.id as product_id, p.name, p.category, p.base_price,
               v.id as variant_id, v.size, v.flavor, v.price, v.stock
        FROM products p
        JOIN product_variants v ON p.id = v.product_id
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


@app.put("/inventory/stock")
def update_stock(body: StockUpdate):
    if body.stock < 0:
        raise HTTPException(status_code=400, detail="stock cannot be negative")
    conn = get_connection()
    conn.execute(
        "UPDATE product_variants SET stock=? WHERE id=?",
        (body.stock, body.variant_id),
    )
    conn.commit()
    conn.close()
    return {"variant_id": body.variant_id, "stock": body.stock}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats")
def dashboard_stats():
    conn = get_connection()

    today_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE DATE(created_at) = DATE('now')"
    ).fetchone()[0]

    today_revenue = conn.execute(
        "SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE DATE(created_at) = DATE('now') AND status != 'cancelled'"
    ).fetchone()[0]

    pending_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE status='pending'"
    ).fetchone()[0]

    total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    total_revenue = conn.execute(
        "SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE status != 'cancelled'"
    ).fetchone()[0]

    pending_returns = conn.execute(
        "SELECT COUNT(*) FROM returns WHERE status='requested'"
    ).fetchone()[0]

    pending_escalations = conn.execute(
        "SELECT COUNT(*) FROM escalations WHERE status='pending'"
    ).fetchone()[0]

    low_stock_items = conn.execute(
        "SELECT COUNT(*) FROM product_variants WHERE stock > 0 AND stock <= 5"
    ).fetchone()[0]

    out_of_stock = conn.execute(
        "SELECT COUNT(*) FROM product_variants WHERE stock = 0"
    ).fetchone()[0]

    conn.close()
    return {
        "today": {
            "orders":  today_orders,
            "revenue": round(today_revenue, 2),
        },
        "total": {
            "orders":  total_orders,
            "revenue": round(total_revenue, 2),
        },
        "pending_orders":      pending_orders,
        "pending_returns":     pending_returns,
        "pending_escalations": pending_escalations,
        "low_stock_items":     low_stock_items,
        "out_of_stock_items":  out_of_stock,
    }


# ── Escalations ───────────────────────────────────────────────────────────────

@app.get("/escalations")
def list_escalations(status: Optional[str] = "pending"):
    conn = get_connection()
    q = "SELECT * FROM escalations"
    params = []
    if status:
        q += " WHERE status=?"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT 50"
    rows = rows_to_list(conn.execute(q, params).fetchall())
    conn.close()
    return rows


@app.patch("/escalations/{escalation_id}/resolve")
def resolve_escalation(escalation_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE escalations SET status='resolved' WHERE id=?", (escalation_id,)
    )
    conn.commit()
    conn.close()
    return {"escalation_id": escalation_id, "status": "resolved"}


# ── Customers ─────────────────────────────────────────────────────────────────

@app.get("/customers")
def list_customers():
    conn = get_connection()
    rows = rows_to_list(conn.execute(
        "SELECT id, name, phone, email, created_at FROM customers ORDER BY created_at DESC"
    ).fetchall())
    conn.close()
    return rows
