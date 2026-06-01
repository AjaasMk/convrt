"""
All LangChain tools available to the SpiceNutrition sales agent.
Each tool hits SQLite and/or ChromaDB directly.

Variant dimensions:  size = pack size/count, flavor = flavour.
"""
import json
import uuid
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from database.models import get_connection, rows_to_list, row_to_dict

CHROMA_PATH = Path(__file__).parent.parent / "chroma_db"
KB_FILE = Path(__file__).parent.parent / "knowledge" / "spicenutrition.txt"
COLLECTION_NAME = "spicenutrition_products"
_chroma_col = None


def _get_collection():
    global _chroma_col
    if _chroma_col is None:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            _chroma_col = client.get_or_create_collection(COLLECTION_NAME)
        except Exception:
            _chroma_col = None
    return _chroma_col


# ── 1. Search Products ────────────────────────────────────────────────────────

@tool
def search_products(
    query: str,
    budget_max: Optional[float] = None,
    size: Optional[str] = None,
    flavor: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """
    Search for supplement products using natural language.
    Returns matching products with prices and availability.
    Use this for product discovery and goal-based recommendations.

    Args:
        query:      Natural language search (e.g. "vegan protein for muscle gain")
        budget_max: Maximum price in INR (optional)
        size:       Pack size like "1kg", "60 tablets", "300g" (optional)
        flavor:     Preferred flavour like "Chocolate", "Unflavored" (optional)
        category:   Category filter: 'Protein', 'Pre-Workout', 'Creatine', 'Amino Acids', 'Vitamins & Wellness', 'Recovery' (optional)
    """
    col = _get_collection()
    results = []

    if col is not None:
        try:
            res = col.query(
                query_texts=[query],
                n_results=5,
                where={"category": {"$ne": "policy"}},
            )
            if res["documents"]:
                names = [m["name"] for m in res["metadatas"][0]]
                results = _fetch_products_by_names(names)
        except Exception:
            pass

    if not results:
        results = _fetch_products_by_filters(size, flavor, category, budget_max)

    if not results:
        return "No products found matching your criteria. Try different filters."

    out = []
    for p in results[:5]:
        variants_info = _variant_summary(p["id"], size, flavor)
        out.append(
            f"• **{p['name']}** ({p['category']})\n"
            f"  {p['description'][:120]}...\n"
            f"  {variants_info}"
        )
    return "\n\n".join(out)


def _fetch_products_by_names(names: list[str]) -> list:
    conn = get_connection()
    placeholders = ",".join("?" * len(names))
    rows = conn.execute(
        f"SELECT * FROM products WHERE name IN ({placeholders})", names
    ).fetchall()
    conn.close()
    return rows_to_list(rows)


def _fetch_products_by_filters(size=None, flavor=None, category=None, budget_max=None) -> list:
    conn = get_connection()
    query = "SELECT DISTINCT p.* FROM products p JOIN product_variants v ON p.id=v.product_id WHERE 1=1"
    params = []
    if size:
        query += " AND LOWER(v.size)=LOWER(?)"
        params.append(size)
    if flavor:
        query += " AND LOWER(v.flavor)=LOWER(?)"
        params.append(flavor)
    if category:
        query += " AND LOWER(p.category) LIKE LOWER(?)"
        params.append(f"%{category}%")
    if budget_max:
        query += " AND v.price<=?"
        params.append(budget_max)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows_to_list(rows)


def _variant_summary(product_id: int, size=None, flavor=None) -> str:
    conn = get_connection()
    q = "SELECT size, flavor, price, stock FROM product_variants WHERE product_id=? AND stock>0"
    params = [product_id]
    if size:
        q += " AND LOWER(size)=LOWER(?)"
        params.append(size)
    if flavor:
        q += " AND LOWER(flavor)=LOWER(?)"
        params.append(flavor)
    rows = rows_to_list(conn.execute(q, params).fetchall())
    conn.close()
    if not rows:
        return "  ⚠️ Currently out of stock"
    prices = sorted({r["price"] for r in rows})
    price_str = f"₹{prices[0]:.0f}" + (f" – ₹{prices[-1]:.0f}" if len(prices) > 1 else "")
    sizes   = sorted({r["size"]   for r in rows})
    flavors = sorted({r["flavor"] for r in rows})
    return f"  Price: {price_str} | Sizes: {', '.join(sizes)} | Flavours: {', '.join(flavors)}"


# ── 2. Check Inventory ────────────────────────────────────────────────────────

@tool
def check_inventory(
    product_name: str,
    size: Optional[str] = None,
    flavor: Optional[str] = None,
) -> str:
    """
    Check real-time stock for a specific supplement.
    Returns available sizes, flavours, and quantities.

    Args:
        product_name: Exact or partial product name
        size:         Specific pack size to check, e.g. "1kg" (optional)
        flavor:       Specific flavour to check (optional)
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT p.name, v.size, v.flavor, v.price, v.stock
        FROM products p
        JOIN product_variants v ON p.id = v.product_id
        WHERE LOWER(p.name) LIKE LOWER(?)
        """,
        (f"%{product_name}%",),
    ).fetchall()
    conn.close()

    if not rows:
        return f"Product '{product_name}' not found. Use search_products to find available items."

    rows = rows_to_list(rows)
    if size:
        rows = [r for r in rows if r["size"].lower() == size.lower()]
    if flavor:
        rows = [r for r in rows if r["flavor"].lower() == flavor.lower()]

    if not rows:
        return f"No variants found for '{product_name}' with the given size/flavour filters."

    pname = rows[0]["name"]
    in_stock  = [r for r in rows if r["stock"] > 0]
    out_stock = [r for r in rows if r["stock"] == 0]

    lines = [f"**{pname}** inventory:"]
    if in_stock:
        lines.append("✅ In stock:")
        for r in in_stock:
            lines.append(f"  {r['size']} / {r['flavor']} — {r['stock']} units @ ₹{r['price']:.0f}")
    if out_stock:
        lines.append("❌ Out of stock:")
        for r in out_stock:
            lines.append(f"  {r['size']} / {r['flavor']}")

    return "\n".join(lines)


# ── 3. Create Order ───────────────────────────────────────────────────────────

@tool
def create_order(
    customer_phone: str,
    items: str,
    delivery_address: Optional[str] = None,
) -> str:
    """
    Place a new order for the customer.

    Args:
        customer_phone: Customer's WhatsApp/phone number
        items: JSON array of objects with keys: product_name, size, flavor, quantity
               Example: '[{"product_name":"Whey Protein Isolate","size":"1kg","flavor":"Chocolate","quantity":1}]'
        delivery_address: Delivery address (uses saved address if not provided)
    """
    try:
        item_list = json.loads(items)
    except json.JSONDecodeError:
        return "Invalid items format. Please provide a valid JSON array."

    conn = get_connection()

    cust = row_to_dict(
        conn.execute("SELECT * FROM customers WHERE phone=?", (customer_phone,)).fetchone()
    )
    if not cust:
        conn.execute(
            "INSERT OR IGNORE INTO customers (name, phone) VALUES (?,?)",
            ("Customer", customer_phone),
        )
        conn.commit()
        cust = row_to_dict(
            conn.execute("SELECT * FROM customers WHERE phone=?", (customer_phone,)).fetchone()
        )

    address = delivery_address or cust.get("address") or "Address to be confirmed"

    order_id = f"SN{uuid.uuid4().hex[:8].upper()}"
    total = 0.0
    resolved = []
    errors = []

    for item in item_list:
        pname  = item.get("product_name", "")
        size   = item.get("size", "")
        flavor = item.get("flavor", "")
        qty    = int(item.get("quantity", 1))

        row = conn.execute(
            """
            SELECT v.id, v.price, v.stock, p.name
            FROM product_variants v
            JOIN products p ON p.id = v.product_id
            WHERE LOWER(p.name) LIKE LOWER(?)
              AND LOWER(v.size) = LOWER(?)
              AND LOWER(v.flavor) = LOWER(?)
            """,
            (f"%{pname}%", size, flavor),
        ).fetchone()

        if not row:
            errors.append(f"'{pname}' in size {size}/{flavor} not found.")
            continue
        row = dict(row)
        if row["stock"] < qty:
            errors.append(f"'{row['name']}' {size}/{flavor}: only {row['stock']} in stock (requested {qty}).")
            continue
        resolved.append((row["id"], qty, row["price"], row["name"]))
        total += row["price"] * qty

    if errors:
        conn.close()
        return "⚠️ Could not place order:\n" + "\n".join(errors)

    conn.execute(
        "INSERT INTO orders (id, customer_id, status, total_amount, delivery_address) VALUES (?,?,?,?,?)",
        (order_id, cust["id"], "pending", total, address),
    )
    for vid, qty, price, _ in resolved:
        conn.execute(
            "INSERT INTO order_items (order_id, variant_id, quantity, unit_price) VALUES (?,?,?,?)",
            (order_id, vid, qty, price),
        )
        conn.execute(
            "UPDATE product_variants SET stock = stock - ? WHERE id = ?",
            (qty, vid),
        )

    conn.commit()
    conn.close()

    item_lines = "\n".join(f"  • {name} ×{qty} — ₹{price*qty:.0f}" for _, qty, price, name in resolved)
    return (
        f"✅ Order placed successfully!\n"
        f"Order ID: **{order_id}**\n"
        f"Items:\n{item_lines}\n"
        f"Total: ₹{total:.0f}\n"
        f"Delivery to: {address}\n"
        f"Estimated delivery: 3–5 business days.\n"
        f"You'll receive a tracking link on WhatsApp once dispatched."
    )


# ── 4. Get Order Status ───────────────────────────────────────────────────────

@tool
def get_order_status(
    order_id: Optional[str] = None,
    customer_phone: Optional[str] = None,
) -> str:
    """
    Track an existing order by Order ID or customer phone number.

    Args:
        order_id:       Order ID starting with 'SN' (optional)
        customer_phone: Customer's phone number to fetch all their orders (optional)
    """
    conn = get_connection()

    if order_id:
        row = conn.execute(
            """
            SELECT o.*, c.name as customer_name
            FROM orders o JOIN customers c ON c.id = o.customer_id
            WHERE o.id = ?
            """,
            (order_id.upper(),),
        ).fetchone()
        if not row:
            conn.close()
            return f"Order '{order_id}' not found. Please check the Order ID."
        order = dict(row)
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

        status_emoji = {"pending": "⏳", "processing": "🔄", "shipped": "🚚", "delivered": "✅", "cancelled": "❌"}.get(order["status"], "📦")
        item_lines = "\n".join(f"  • {i['name']} ({i['size']}/{i['flavor']}) ×{i['quantity']}" for i in items)
        return (
            f"{status_emoji} **Order {order['id']}**\n"
            f"Status: {order['status'].upper()}\n"
            f"Items:\n{item_lines}\n"
            f"Total: ₹{order['total_amount']:.0f}\n"
            f"Placed on: {order['created_at'][:10]}"
        )

    elif customer_phone:
        orders = rows_to_list(conn.execute(
            """
            SELECT o.id, o.status, o.total_amount, o.created_at
            FROM orders o JOIN customers c ON c.id = o.customer_id
            WHERE c.phone = ?
            ORDER BY o.created_at DESC LIMIT 5
            """,
            (customer_phone,),
        ).fetchall())
        conn.close()
        if not orders:
            return "No orders found for this number."
        lines = [f"📦 Your recent orders:"]
        for o in orders:
            emoji = {"pending": "⏳", "processing": "🔄", "shipped": "🚚", "delivered": "✅", "cancelled": "❌"}.get(o["status"], "📦")
            lines.append(f"  {emoji} {o['id']} — {o['status'].upper()} — ₹{o['total_amount']:.0f} ({o['created_at'][:10]})")
        return "\n".join(lines)

    conn.close()
    return "Please provide either an Order ID or phone number."


# ── 5. Process Return ─────────────────────────────────────────────────────────

@tool
def process_return(order_id: str, reason: str) -> str:
    """
    Initiate a return or replacement request for an order.
    Note: opened supplement tubs are only returnable if damaged/defective.

    Args:
        order_id: The Order ID (e.g. SN1A2B3C4D)
        reason:   Reason for return (damaged, leaking, wrong item, sealed/unopened, near expiry, etc.)
    """
    conn = get_connection()
    order = row_to_dict(conn.execute(
        "SELECT * FROM orders WHERE id=?", (order_id.upper(),)
    ).fetchone())

    if not order:
        conn.close()
        return f"Order '{order_id}' not found."

    if order["status"] not in ("delivered", "shipped"):
        conn.close()
        return f"Return not applicable — order status is '{order['status']}'. Returns are only for delivered orders."

    existing = conn.execute(
        "SELECT id FROM returns WHERE order_id=?", (order_id.upper(),)
    ).fetchone()
    if existing:
        conn.close()
        return f"A return request for order {order_id} already exists. Our team will contact you shortly."

    conn.execute(
        "INSERT INTO returns (order_id, reason, status) VALUES (?,?,?)",
        (order_id.upper(), reason, "requested"),
    )
    conn.commit()
    conn.close()

    return (
        f"✅ Return request submitted for Order **{order_id.upper()}**.\n"
        f"Reason: {reason}\n\n"
        f"Note: for hygiene reasons, only sealed/unopened products are returnable "
        f"(opened items only if damaged or defective). Our team will reach out within "
        f"24 hours to arrange pickup. Refund/replacement is processed within 5–7 business days."
    )


# ── 6. Add to Waitlist ────────────────────────────────────────────────────────

@tool
def add_to_waitlist(
    product_name: str,
    size: str,
    flavor: str,
    customer_phone: str,
) -> str:
    """
    Add a customer to the waitlist for an out-of-stock item.
    They will be notified when it's back in stock.

    Args:
        product_name:   Product name
        size:           Required pack size (e.g. "1kg")
        flavor:         Required flavour
        customer_phone: Customer's phone number
    """
    conn = get_connection()

    variant = conn.execute(
        """
        SELECT v.id, p.name
        FROM product_variants v
        JOIN products p ON p.id = v.product_id
        WHERE LOWER(p.name) LIKE LOWER(?)
          AND LOWER(v.size) = LOWER(?)
          AND LOWER(v.flavor) = LOWER(?)
        """,
        (f"%{product_name}%", size, flavor),
    ).fetchone()

    if not variant:
        conn.close()
        return f"Could not find '{product_name}' in size {size}/{flavor}."

    variant = dict(variant)

    cust = row_to_dict(conn.execute(
        "SELECT id FROM customers WHERE phone=?", (customer_phone,)
    ).fetchone())
    if not cust:
        conn.execute(
            "INSERT OR IGNORE INTO customers (name, phone) VALUES (?,?)",
            ("Customer", customer_phone),
        )
        conn.commit()
        cust = row_to_dict(conn.execute(
            "SELECT id FROM customers WHERE phone=?", (customer_phone,)
        ).fetchone())

    existing = conn.execute(
        "SELECT id FROM waitlist WHERE variant_id=? AND customer_id=?",
        (variant["id"], cust["id"]),
    ).fetchone()
    if existing:
        conn.close()
        return f"You're already on the waitlist for {variant['name']} ({size}/{flavor}). We'll notify you!"

    conn.execute(
        "INSERT INTO waitlist (variant_id, customer_id) VALUES (?,?)",
        (variant["id"], cust["id"]),
    )
    conn.commit()
    conn.close()

    return (
        f"✅ Added to waitlist for **{variant['name']}** (Size: {size}, Flavour: {flavor}).\n"
        f"We'll send you a WhatsApp message as soon as it's restocked!"
    )


# ── 7. Get Store Info (RAG) ───────────────────────────────────────────────────

@tool
def get_store_info(query: str) -> str:
    """
    Retrieve store policies, FAQs, return policy, delivery info,
    dosage/usage guides, certifications, and other SpiceNutrition information.

    Args:
        query: Question about the store (e.g. "when should I take creatine?")
    """
    col = _get_collection()
    if col is None:
        if KB_FILE.exists():
            return KB_FILE.read_text(encoding="utf-8")[:2000]
        return "Store information unavailable."

    try:
        res = col.query(
            query_texts=[query],
            n_results=3,
            where={"category": {"$eq": "policy"}},
        )
        docs = res["documents"][0] if res["documents"] else []
        if docs:
            return "\n\n---\n\n".join(docs)
    except Exception:
        pass

    if KB_FILE.exists():
        return KB_FILE.read_text(encoding="utf-8")[:2000]
    return "Store information unavailable."


# ── 8. Escalate to Human ──────────────────────────────────────────────────────

@tool
def escalate_to_human(customer_phone: str, issue: str) -> str:
    """
    Escalate a complex or sensitive issue to the human support team.
    Use this when the customer is very upset, requests a refund beyond policy,
    mentions legal action, OR reports any adverse reaction / side effect / health
    concern after using a supplement.

    Args:
        customer_phone: Customer's phone number
        issue:          Summary of the issue to escalate
    """
    conn = get_connection()
    cust = row_to_dict(conn.execute(
        "SELECT id FROM customers WHERE phone=?", (customer_phone,)
    ).fetchone())
    customer_id = cust.get("id") if cust else None

    conn.execute(
        "INSERT INTO escalations (customer_id, customer_phone, issue, status) VALUES (?,?,?,?)",
        (customer_id, customer_phone, issue, "pending"),
    )
    conn.commit()
    conn.close()

    return (
        "I've escalated your issue to our senior support team. "
        "A SpiceNutrition representative will contact you within 2 hours on this WhatsApp number. "
        "If this is about a health concern or reaction, please stop use and consult a doctor. "
        "We appreciate your patience. 🙏"
    )


# ── 9. Get Website Link ───────────────────────────────────────────────────────

@tool
def get_website_link() -> str:
    """
    Return the SpiceNutrition website URL for browsing the full catalogue.
    Use when the customer wants to browse products online.
    """
    return (
        "🛒 Browse our full range at: **https://spicenutrition.in**\n"
        "You'll find all proteins, pre-workouts, creatine, vitamins, lab reports, and stack deals there. "
        "You can also place orders directly on the website!"
    )


# ── Tool registry ─────────────────────────────────────────────────────────────

def get_tools() -> list:
    return [
        search_products,
        check_inventory,
        create_order,
        get_order_status,
        process_return,
        add_to_waitlist,
        get_store_info,
        escalate_to_human,
        get_website_link,
    ]
