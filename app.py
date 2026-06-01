"""
Convrt – WhatsApp AI Sales Agent for SpiceNutrition
Gradio UI with 3 tabs: Customer Chat | Staff Dashboard | Inventory Manager

Run:  python app.py
"""
import os
import uuid
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from database.models import init_db, get_connection, rows_to_list
from database.seed_data import seed_all
from agent.graph import chat

import gradio as gr

# ── Init ──────────────────────────────────────────────────────────────────────

seed_all()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_stats() -> dict:
    conn = get_connection()
    today_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE DATE(created_at)=DATE('now')"
    ).fetchone()[0]
    today_revenue = conn.execute(
        "SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE DATE(created_at)=DATE('now') AND status!='cancelled'"
    ).fetchone()[0]
    total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    total_revenue = conn.execute(
        "SELECT COALESCE(SUM(total_amount),0) FROM orders WHERE status!='cancelled'"
    ).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
    returns = conn.execute("SELECT COUNT(*) FROM returns WHERE status='requested'").fetchone()[0]
    escalations = conn.execute("SELECT COUNT(*) FROM escalations WHERE status='pending'").fetchone()[0]
    conn.close()
    return {
        "today_orders":   today_orders,
        "today_revenue":  round(today_revenue, 2),
        "total_orders":   total_orders,
        "total_revenue":  round(total_revenue, 2),
        "pending":        pending,
        "returns":        returns,
        "escalations":    escalations,
    }


def _get_recent_orders(limit: int = 30) -> list[list]:
    conn = get_connection()
    rows = rows_to_list(conn.execute(
        """
        SELECT o.id, c.name, c.phone, o.status,
               printf('₹%.0f', o.total_amount) as amount,
               o.created_at
        FROM orders o JOIN customers c ON c.id=o.customer_id
        ORDER BY o.created_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall())
    conn.close()
    return [[r["id"], r["name"], r["phone"], r["status"], r["amount"], r["created_at"][:16]] for r in rows]


def _get_escalations() -> list[list]:
    conn = get_connection()
    rows = rows_to_list(conn.execute(
        "SELECT id, customer_phone, issue, status, created_at FROM escalations ORDER BY created_at DESC LIMIT 20"
    ).fetchall())
    conn.close()
    return [[r["id"], r["customer_phone"], r["issue"][:80], r["status"], r["created_at"][:16]] for r in rows]


def _get_inventory() -> list[list]:
    conn = get_connection()
    rows = rows_to_list(conn.execute(
        """
        SELECT v.id, p.name, p.category, v.size, v.flavor,
               printf('₹%.0f', v.price) as price, v.stock
        FROM product_variants v JOIN products p ON p.id=v.product_id
        ORDER BY p.name, v.size, v.flavor
        """
    ).fetchall())
    conn.close()
    return [[r["id"], r["name"], r["category"], r["size"], r["flavor"], r["price"], r["stock"]] for r in rows]


def _get_low_stock() -> list[list]:
    conn = get_connection()
    rows = rows_to_list(conn.execute(
        """
        SELECT v.id, p.name, v.size, v.flavor, v.stock
        FROM product_variants v JOIN products p ON p.id=v.product_id
        WHERE v.stock <= 5
        ORDER BY v.stock ASC, p.name
        """
    ).fetchall())
    conn.close()
    return [[r["id"], r["name"], r["size"], r["flavor"], r["stock"]] for r in rows]


# ── Tab 1: Customer Chat ──────────────────────────────────────────────────────

from agent import handoff


def _build_customer_view(session_id: str) -> list:
    """Render the DB transcript for the customer's WhatsApp-style view."""
    view = []
    for m in handoff.get_messages(session_id):
        if m["role"] == "customer":
            view.append({"role": "user", "content": m["content"]})
        elif m["role"] == "ai":
            view.append({"role": "assistant", "content": m["content"]})
        elif m["role"] == "staff":
            view.append({"role": "assistant", "content": "👤 **Team:** " + m["content"]})
    return view


def send_message(user_message: str, history: list, session_id: str, customer_phone: str):
    if not user_message.strip():
        return _build_customer_view(session_id), session_id, ""

    if not session_id:
        session_id = str(uuid.uuid4())

    phone = customer_phone.strip() or "unknown"

    try:
        chat(user_message.strip(), session_id, phone)  # logs msg + AI reply (if in AI mode)
    except Exception as e:
        handoff.log_message(session_id, "ai", f"⚠️ Agent error: {e}")

    return _build_customer_view(session_id), session_id, ""


def poll_customer(session_id: str):
    """Timer tick — pulls in any new staff replies so the customer sees them live."""
    if not session_id:
        return gr.update()
    return _build_customer_view(session_id)


def clear_chat():
    return [], str(uuid.uuid4()), ""


# ── Human handoff (staff side) ────────────────────────────────────────────────

def _conv_label(c: dict) -> str:
    bell = "🔔 " if c["needs_attention"] else ""
    mode = "🧑 human" if c["mode"] == "human" else "🤖 AI"
    phone = c["customer_phone"] or "unknown"
    return f"{bell}{phone} · {mode} · {c['msg_count']} msgs · {c['session_id'][:8]}"


def refresh_conversations():
    convs = handoff.list_conversations()
    choices = [(_conv_label(c), c["session_id"]) for c in convs]
    attention = sum(1 for c in convs if c["needs_attention"])
    banner = (f"🔔 **{attention} conversation(s) need attention**"
              if attention else "✅ No conversations need attention")
    return gr.update(choices=choices), banner


def _build_staff_view(session_id: str) -> list:
    view = []
    for m in handoff.get_messages(session_id):
        if m["role"] == "customer":
            view.append({"role": "user", "content": m["content"]})
        elif m["role"] == "ai":
            view.append({"role": "assistant", "content": "🤖 " + m["content"]})
        elif m["role"] == "staff":
            view.append({"role": "assistant", "content": "👤 **You:** " + m["content"]})
    return view


def load_conversation(session_id: str):
    if not session_id:
        return [], "_Select a conversation._"
    handoff.maybe_auto_resume(session_id)
    mode = handoff.get_mode(session_id)
    label = "🧑 HUMAN mode — AI paused" if mode == "human" else "🤖 AI mode — agent is replying"
    return _build_staff_view(session_id), f"**Status:** {label}"


def staff_typing(session_id: str):
    """Staff focused/started typing → take over, pause AI immediately."""
    if session_id:
        handoff.staff_start_typing(session_id)
    return "**Status:** 🧑 HUMAN mode — AI paused (you're typing)"


def staff_reply(session_id: str, text: str):
    if not session_id or not text.strip():
        return _build_staff_view(session_id), "", "**Status:** enter a message."
    handoff.staff_send(session_id, text.strip())
    return _build_staff_view(session_id), "", "**Status:** 🧑 HUMAN mode — reply sent"


def staff_resume_ai(session_id: str):
    if session_id:
        handoff.resume_ai(session_id)
    return _build_staff_view(session_id), "**Status:** 🤖 AI mode — agent resumed"


# ── Tab 2: Staff Dashboard ────────────────────────────────────────────────────

def refresh_dashboard():
    s = _get_stats()
    stats_md = f"""
### 📊 Today's Performance
| Metric | Value |
|--------|-------|
| 🛒 Orders Today | **{s['today_orders']}** |
| 💰 Revenue Today | **₹{s['today_revenue']:,.0f}** |
| 📦 Total Orders | {s['total_orders']} |
| 💵 Total Revenue | ₹{s['total_revenue']:,.0f} |
| ⏳ Pending Orders | {s['pending']} |
| 🔄 Pending Returns | {s['returns']} |
| 🚨 Open Escalations | **{s['escalations']}** |

*Last refreshed: {datetime.now().strftime('%H:%M:%S')}*
"""
    orders = _get_recent_orders()
    escalations = _get_escalations()
    return stats_md, orders, escalations


def resolve_escalation_fn(escalation_id_str: str):
    if not escalation_id_str.strip():
        return "Enter an escalation ID first.", *refresh_dashboard()
    try:
        eid = int(escalation_id_str.strip())
    except ValueError:
        return "Invalid escalation ID.", *refresh_dashboard()
    conn = get_connection()
    conn.execute("UPDATE escalations SET status='resolved' WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    msg, orders, escalations = refresh_dashboard()
    return f"✅ Escalation #{eid} resolved.", msg, orders, escalations


def update_order_status_fn(order_id: str, new_status: str):
    if not order_id.strip():
        return "Enter an Order ID.", *refresh_dashboard()
    conn = get_connection()
    conn.execute(
        "UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (new_status, order_id.strip().upper()),
    )
    conn.commit()
    conn.close()
    msg, orders, escalations = refresh_dashboard()
    return f"✅ Order {order_id.upper()} → {new_status}", msg, orders, escalations


# ── Tab 3: Inventory Manager ──────────────────────────────────────────────────

def refresh_inventory():
    return _get_inventory(), _get_low_stock()


def update_stock_fn(variant_id_str: str, new_stock_str: str):
    if not variant_id_str.strip() or not new_stock_str.strip():
        return "Fill both Variant ID and new stock.", *refresh_inventory()
    try:
        vid = int(variant_id_str.strip())
        stock = int(new_stock_str.strip())
    except ValueError:
        return "Variant ID and stock must be integers.", *refresh_inventory()
    if stock < 0:
        return "Stock cannot be negative.", *refresh_inventory()
    conn = get_connection()
    conn.execute("UPDATE product_variants SET stock=? WHERE id=?", (stock, vid))
    conn.commit()
    conn.close()
    inv, low = refresh_inventory()
    return f"✅ Variant #{vid} stock updated to {stock}.", inv, low


# ── Gradio Layout ─────────────────────────────────────────────────────────────

BRAND_CSS = """
:root { --sn-blue: #1565C0; --sn-blue-light: #42A5F5; --sn-blue-pale: #E3F2FD; }
.chat-bubble-user   { background: var(--sn-blue-pale) !important; border-radius: 18px 18px 4px 18px !important; }
.chat-bubble-bot    { background: #FFFFFF !important; border-radius: 18px 18px 18px 4px !important; }
#chat-window        { background: #F5F9FF; }
.gradio-container   { font-family: 'Segoe UI', sans-serif; }
#sn-header          { background: linear-gradient(135deg, #1565C0 0%, #42A5F5 100%);
                      color: #FFFFFF; padding: 18px 24px; border-radius: 12px; margin-bottom: 8px; }
#sn-header h1, #sn-header h3 { color: #FFFFFF !important; margin: 0; }
.tab-nav button.selected { color: var(--sn-blue) !important; border-bottom-color: var(--sn-blue) !important; }
button.primary { background: var(--sn-blue) !important; border-color: var(--sn-blue) !important; }
"""

with gr.Blocks(title="Convrt – SpiceNutrition AI Agent") as demo:
    gr.HTML(
        """
        <div id="sn-header">
          <h1>💪 Convrt — WhatsApp AI Sales Agent</h1>
          <h3>SpiceNutrition · <em>Fuel Your Performance</em></h3>
        </div>
        """
    )

    with gr.Tabs():

        # ── Tab 1: Customer Chat ──────────────────────────────────────────────
        with gr.TabItem("💬 Customer Chat"):
            gr.Markdown("Simulate a WhatsApp conversation with the SpiceNutrition AI agent.")

            with gr.Row():
                with gr.Column(scale=1):
                    customer_phone_input = gr.Textbox(
                        label="Customer WhatsApp Number",
                        placeholder="+91XXXXXXXXXX",
                        value="+919876543210",
                    )
                    session_id_state = gr.State(str(uuid.uuid4()))
                    gr.Markdown("**Session ID** is auto-generated per conversation.")

            chatbot = gr.Chatbot(
                label="SpiceNutrition Chat",
                elem_id="chat-window",
                height=500,
                render_markdown=True,
                placeholder="Start chatting with SpiceNutrition AI...",
            )
            # Live poll so staff replies (human takeover) appear for the customer.
            customer_timer = gr.Timer(3.0)

            with gr.Row():
                msg_input = gr.Textbox(
                    label="",
                    placeholder="Type a message...",
                    scale=5,
                    container=False,
                )
                send_btn = gr.Button("Send ➤", variant="primary", scale=1)
                clear_btn = gr.Button("🗑 Clear", scale=1)

            gr.Examples(
                examples=[
                    ["Hi! I want to build muscle. What protein do you recommend under ₹3000?"],
                    ["Do you have Whey Protein Isolate in 1kg, Chocolate?"],
                    ["When should I take creatine, and do I need to load it?"],
                    ["I want to order Creatine Monohydrate 250g Unflavored. Address: 5 Park St, Kolkata."],
                    ["Can you check my recent orders?"],
                    ["Do you have a vegan protein option?"],
                    ["I felt sick after taking the pre-workout, I want a refund!"],
                    ["Do you have a website I can browse?"],
                ],
                inputs=msg_input,
                label="Quick Examples",
            )

            # Wire up
            send_btn.click(
                send_message,
                inputs=[msg_input, chatbot, session_id_state, customer_phone_input],
                outputs=[chatbot, session_id_state, msg_input],
            )
            msg_input.submit(
                send_message,
                inputs=[msg_input, chatbot, session_id_state, customer_phone_input],
                outputs=[chatbot, session_id_state, msg_input],
            )
            clear_btn.click(clear_chat, outputs=[chatbot, session_id_state, msg_input])
            customer_timer.tick(poll_customer, inputs=session_id_state, outputs=chatbot)

        # ── Tab 2: Staff Dashboard ────────────────────────────────────────────
        with gr.TabItem("📊 Staff Dashboard"):
            gr.Markdown("Real-time view of orders, revenue, and escalations.")

            with gr.Row():
                refresh_dash_btn = gr.Button("🔄 Refresh", variant="primary")

            stats_display = gr.Markdown()

            gr.Markdown("### 🛒 Recent Orders")
            orders_table = gr.Dataframe(
                headers=["Order ID", "Customer", "Phone", "Status", "Amount", "Date"],
                datatype=["str", "str", "str", "str", "str", "str"],
                interactive=False,
                wrap=True,
            )

            with gr.Row():
                order_id_input  = gr.Textbox(label="Order ID", placeholder="SH1A2B3C4D")
                order_status_dd = gr.Dropdown(
                    choices=["pending", "processing", "shipped", "delivered", "cancelled"],
                    label="New Status",
                    value="processing",
                )
                update_order_btn = gr.Button("Update Order Status", variant="secondary")
            order_update_msg = gr.Markdown()

            gr.Markdown("### 🚨 Escalations")
            escalations_table = gr.Dataframe(
                headers=["ID", "Phone", "Issue", "Status", "Date"],
                datatype=["number", "str", "str", "str", "str"],
                interactive=False,
                wrap=True,
            )

            with gr.Row():
                escalation_id_input = gr.Textbox(label="Escalation ID to Resolve", placeholder="1")
                resolve_btn = gr.Button("✅ Mark Resolved", variant="secondary")
            escalation_msg = gr.Markdown()

            # Wire up
            refresh_dash_btn.click(
                refresh_dashboard,
                outputs=[stats_display, orders_table, escalations_table],
            )
            update_order_btn.click(
                update_order_status_fn,
                inputs=[order_id_input, order_status_dd],
                outputs=[order_update_msg, stats_display, orders_table, escalations_table],
            )
            resolve_btn.click(
                resolve_escalation_fn,
                inputs=[escalation_id_input],
                outputs=[escalation_msg, stats_display, orders_table, escalations_table],
            )

            # ── Live Conversations / Human Takeover ───────────────────────────
            gr.Markdown("---")
            gr.Markdown("### 🧑‍💼 Live Conversations — Human Takeover")
            handoff_banner = gr.Markdown("✅ No conversations need attention")
            with gr.Row():
                conv_dropdown = gr.Dropdown(
                    label="Select a conversation",
                    choices=[],
                    interactive=True,
                    scale=4,
                )
                refresh_conv_btn = gr.Button("🔄 Refresh", scale=1)
            conv_status = gr.Markdown("_Select a conversation._")
            staff_chat = gr.Chatbot(
                label="Conversation transcript",
                height=320,
                render_markdown=True,
            )
            with gr.Row():
                staff_reply_box = gr.Textbox(
                    label="",
                    placeholder="Type to take over — the AI pauses the moment you start typing…",
                    scale=5,
                    container=False,
                )
                staff_send_btn = gr.Button("Send as staff ➤", variant="primary", scale=1)
                resume_ai_btn = gr.Button("🤖 Resume AI", scale=1)
            conv_timer = gr.Timer(3.0)

            # Wire up handoff panel
            refresh_conv_btn.click(refresh_conversations, outputs=[conv_dropdown, handoff_banner])
            conv_dropdown.change(load_conversation, inputs=conv_dropdown, outputs=[staff_chat, conv_status])
            # Staff focusing (opening the keyboard) in the box -> AI pauses immediately
            staff_reply_box.focus(staff_typing, inputs=conv_dropdown, outputs=conv_status)
            staff_send_btn.click(
                staff_reply,
                inputs=[conv_dropdown, staff_reply_box],
                outputs=[staff_chat, staff_reply_box, conv_status],
            )
            staff_reply_box.submit(
                staff_reply,
                inputs=[conv_dropdown, staff_reply_box],
                outputs=[staff_chat, staff_reply_box, conv_status],
            )
            resume_ai_btn.click(staff_resume_ai, inputs=conv_dropdown, outputs=[staff_chat, conv_status])
            # Live refresh of the conversation list + open transcript
            conv_timer.tick(refresh_conversations, outputs=[conv_dropdown, handoff_banner])
            conv_timer.tick(load_conversation, inputs=conv_dropdown, outputs=[staff_chat, conv_status])

            demo.load(refresh_dashboard, outputs=[stats_display, orders_table, escalations_table])
            demo.load(refresh_conversations, outputs=[conv_dropdown, handoff_banner])

        # ── Tab 3: Inventory Manager ──────────────────────────────────────────
        with gr.TabItem("📦 Inventory Manager"):
            gr.Markdown("View and manage all product stock levels.")

            with gr.Row():
                refresh_inv_btn = gr.Button("🔄 Refresh Inventory", variant="primary")

            gr.Markdown("### All Products & Variants")
            inventory_table = gr.Dataframe(
                headers=["Variant ID", "Product", "Category", "Size", "Flavour", "Price", "Stock"],
                datatype=["number", "str", "str", "str", "str", "str", "number"],
                interactive=False,
                wrap=True,
            )

            gr.Markdown("### ⚠️ Low Stock Alerts (≤ 5 units)")
            low_stock_table = gr.Dataframe(
                headers=["Variant ID", "Product", "Size", "Flavour", "Stock"],
                datatype=["number", "str", "str", "str", "number"],
                interactive=False,
                wrap=True,
            )

            gr.Markdown("### Update Stock")
            with gr.Row():
                variant_id_input = gr.Textbox(label="Variant ID", placeholder="e.g. 12")
                new_stock_input  = gr.Textbox(label="New Stock Quantity", placeholder="e.g. 25")
                update_stock_btn = gr.Button("Update Stock", variant="secondary")
            stock_update_msg = gr.Markdown()

            # Wire up
            refresh_inv_btn.click(
                refresh_inventory,
                outputs=[inventory_table, low_stock_table],
            )
            update_stock_btn.click(
                update_stock_fn,
                inputs=[variant_id_input, new_stock_input],
                outputs=[stock_update_msg, inventory_table, low_stock_table],
            )

            demo.load(refresh_inventory, outputs=[inventory_table, low_stock_table])


if __name__ == "__main__":
    # Login auth — only users with these credentials can open the app,
    # even if they have the link. Set APP_USERNAME / APP_PASSWORD in .env.
    app_user = os.getenv("APP_USERNAME")
    app_pass = os.getenv("APP_PASSWORD")
    auth = (app_user, app_pass) if app_user and app_pass else None
    if auth:
        print(f"🔐 Login required — username: {app_user}")
    else:
        print("⚠️  No APP_USERNAME/APP_PASSWORD set — app is OPEN (no login).")

    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        auth=auth,
        auth_message="SpiceNutrition Staff Login — Convrt Dashboard",
        theme=gr.themes.Soft(primary_hue="blue", secondary_hue="blue"),
        css=BRAND_CSS,
    )
