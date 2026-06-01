"""
Seed SpiceNutrition database with 15 supplement products, 3 customers,
5 orders, and populate ChromaDB with product knowledge for RAG.
Run:  python -m database.seed_data

Variant dimensions for supplements:
  size  = pack size / count   (e.g. "1kg", "60 caps", "300g")
  flavor = flavour            (e.g. "Chocolate", "Unflavored")
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import get_connection, init_db

# ── Products ─────────────────────────────────────────────────────────────────

PRODUCTS = [
    {
        "name": "Whey Protein Isolate",
        "description": (
            "Ultra-pure whey protein isolate delivering 27g protein and just 1g "
            "carbs per serving. Fast-absorbing, low-lactose, ideal for lean muscle "
            "and post-workout recovery. Third-party lab-tested."
        ),
        "category": "Protein",
        "base_price": 2999.0,
        "variants": [
            {"size": s, "flavor": f, "price": price, "stock": stock}
            for s, price in [("1kg", 2999.0), ("2kg", 5499.0)]
            for f, stock in [("Chocolate", 20), ("Vanilla", 15), ("Strawberry", 10), ("Unflavored", 8)]
        ],
    },
    {
        "name": "Whey Protein Concentrate",
        "description": (
            "Classic whey concentrate with 24g protein per scoop. Great value for "
            "everyday muscle building and recovery. Smooth mixability, no clumps."
        ),
        "category": "Protein",
        "base_price": 2199.0,
        "variants": [
            {"size": s, "flavor": f, "price": price, "stock": stock}
            for s, price in [("1kg", 2199.0), ("2kg", 3999.0)]
            for f, stock in [("Chocolate", 25), ("Vanilla", 18), ("Cookies & Cream", 12)]
        ],
    },
    {
        "name": "Plant Protein (Vegan)",
        "description": (
            "100% plant-based protein from pea and brown rice, 22g protein per serving. "
            "Vegan, dairy-free, easy to digest. Complete amino acid profile."
        ),
        "category": "Protein",
        "base_price": 2499.0,
        "variants": [
            {"size": s, "flavor": f, "price": price, "stock": stock}
            for s, price in [("500g", 1399.0), ("1kg", 2499.0)]
            for f, stock in [("Chocolate", 14), ("Vanilla", 10), ("Unflavored", 6)]
        ],
    },
    {
        "name": "Mass Gainer",
        "description": (
            "High-calorie mass gainer with 50g protein and complex carbs per serving. "
            "Built for hard gainers who struggle to add size. Added digestive enzymes."
        ),
        "category": "Protein",
        "base_price": 2799.0,
        "variants": [
            {"size": s, "flavor": f, "price": price, "stock": stock}
            for s, price in [("1kg", 1599.0), ("3kg", 2799.0)]
            for f, stock in [("Chocolate", 12), ("Banana", 8)]
        ],
    },
    {
        "name": "Pre-Workout Blast",
        "description": (
            "Explosive pre-workout with 200mg caffeine, beta-alanine, and citrulline "
            "for energy, focus, and pumps. 30 servings per tub. Take 20–30 min before training."
        ),
        "category": "Pre-Workout",
        "base_price": 1799.0,
        "variants": [
            {"size": "300g", "flavor": f, "price": 1799.0, "stock": stock}
            for f, stock in [("Fruit Punch", 16), ("Blue Raspberry", 12), ("Watermelon", 9)]
        ],
    },
    {
        "name": "Pump Pre-Workout (Stim-Free)",
        "description": (
            "Caffeine-free pump formula with citrulline and glycerol. Massive pumps "
            "without the jitters — perfect for late-evening training. 25 servings."
        ),
        "category": "Pre-Workout",
        "base_price": 1699.0,
        "variants": [
            {"size": "250g", "flavor": f, "price": 1699.0, "stock": stock}
            for f, stock in [("Green Apple", 11), ("Mango", 7)]
        ],
    },
    {
        "name": "Creatine Monohydrate",
        "description": (
            "Micronised creatine monohydrate, 3g per serving. The most researched "
            "supplement for strength, power, and muscle volume. Mixes clear, no taste."
        ),
        "category": "Creatine",
        "base_price": 899.0,
        "variants": [
            {"size": s, "flavor": f, "price": price, "stock": stock}
            for s, price in [("250g", 899.0), ("500g", 1599.0)]
            for f, stock in [("Unflavored", 30), ("Fruit Punch", 14)]
        ],
    },
    {
        "name": "Creatine HCL",
        "description": (
            "Creatine hydrochloride for superior solubility and no bloating. "
            "Smaller effective dose, gentle on the stomach. 250g, ~83 servings."
        ),
        "category": "Creatine",
        "base_price": 1199.0,
        "variants": [
            {"size": "250g", "flavor": "Unflavored", "price": 1199.0, "stock": 18},
        ],
    },
    {
        "name": "BCAA 2:1:1",
        "description": (
            "Branched-chain amino acids in the proven 2:1:1 ratio for recovery and "
            "intra-workout fuel. Added electrolytes for hydration. Sip during training."
        ),
        "category": "Amino Acids",
        "base_price": 1499.0,
        "variants": [
            {"size": s, "flavor": f, "price": price, "stock": stock}
            for s, price in [("250g", 1499.0), ("450g", 2299.0)]
            for f, stock in [("Watermelon", 13), ("Green Apple", 10), ("Lemon", 5)]
        ],
    },
    {
        "name": "EAA Recovery",
        "description": (
            "Full-spectrum essential amino acids (all 9 EAAs) for complete muscle "
            "recovery and protein synthesis. Refreshing flavours, 30 servings."
        ),
        "category": "Amino Acids",
        "base_price": 1899.0,
        "variants": [
            {"size": "300g", "flavor": f, "price": 1899.0, "stock": stock}
            for f, stock in [("Mango", 9), ("Mixed Berry", 6)]
        ],
    },
    {
        "name": "Multivitamin Daily",
        "description": (
            "Comprehensive daily multivitamin with 23 vitamins and minerals for energy, "
            "immunity, and overall wellness. One tablet a day with a meal."
        ),
        "category": "Vitamins & Wellness",
        "base_price": 699.0,
        "variants": [
            {"size": s, "flavor": "Unflavored", "price": price, "stock": stock}
            for s, price, stock in [("60 tablets", 699.0, 22), ("120 tablets", 1199.0, 15)]
        ],
    },
    {
        "name": "Vitamin D3 + K2",
        "description": (
            "High-potency Vitamin D3 (2000 IU) paired with K2 (MK-7) for bone health, "
            "immunity, and calcium absorption. 60 easy-swallow softgels."
        ),
        "category": "Vitamins & Wellness",
        "base_price": 599.0,
        "variants": [
            {"size": "60 capsules", "flavor": "Unflavored", "price": 599.0, "stock": 19},
        ],
    },
    {
        "name": "Omega-3 Fish Oil",
        "description": (
            "Triple-strength fish oil with 1000mg EPA+DHA per serving for heart, brain, "
            "and joint health. Enteric-coated, no fishy aftertaste."
        ),
        "category": "Vitamins & Wellness",
        "base_price": 899.0,
        "variants": [
            {"size": s, "flavor": "Unflavored", "price": price, "stock": stock}
            for s, price, stock in [("90 softgels", 899.0, 17), ("180 softgels", 1599.0, 9)]
        ],
    },
    {
        "name": "Vitamin C + Zinc",
        "description": (
            "Immune-support combo of 1000mg Vitamin C and 15mg Zinc. Antioxidant "
            "protection and daily immunity. Chewable orange-flavour tablets."
        ),
        "category": "Vitamins & Wellness",
        "base_price": 449.0,
        "variants": [
            {"size": "60 tablets", "flavor": "Orange", "price": 449.0, "stock": 24},
        ],
    },
    {
        "name": "Glutamine",
        "description": (
            "Pure L-Glutamine, 5g per serving, for muscle recovery and gut health. "
            "Unflavored — stack it with your post-workout shake."
        ),
        "category": "Recovery",
        "base_price": 999.0,
        "variants": [
            {"size": s, "flavor": "Unflavored", "price": price, "stock": stock}
            for s, price, stock in [("250g", 999.0, 13), ("500g", 1699.0, 4)]
        ],
    },
]

CUSTOMERS = [
    {"name": "Arjun Mehta",   "phone": "+919876543210", "email": "arjun@example.com",  "address": "12 MG Road, Bengaluru 560001"},
    {"name": "Sneha Reddy",   "phone": "+919876543211", "email": "sneha@example.com",  "address": "45 Jubilee Hills, Hyderabad 500033"},
    {"name": "Vikram Singh",  "phone": "+919876543212", "email": "vikram@example.com", "address": "8 Sector 17, Chandigarh 160017"},
]

SAMPLE_ORDERS = [
    # (customer_index, [(product_name, size, flavor, qty)], status)
    (0, [("Whey Protein Isolate", "1kg", "Chocolate", 1), ("Creatine Monohydrate", "250g", "Unflavored", 1)], "delivered"),
    (1, [("Plant Protein (Vegan)", "1kg", "Vanilla", 1)],                                                      "processing"),
    (2, [("Mass Gainer", "3kg", "Chocolate", 1), ("Pre-Workout Blast", "300g", "Fruit Punch", 1)],            "pending"),
    (0, [("BCAA 2:1:1", "450g", "Watermelon", 1), ("Multivitamin Daily", "60 tablets", "Unflavored", 1)],     "shipped"),
    (1, [("Whey Protein Concentrate", "2kg", "Chocolate", 1), ("Omega-3 Fish Oil", "90 softgels", "Unflavored", 2)], "delivered"),
]


# ── Seeding ───────────────────────────────────────────────────────────────────

def seed_sqlite():
    conn = get_connection()
    cur = conn.cursor()

    if cur.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0:
        print("SQLite already seeded — skipping.")
        conn.close()
        return

    product_id_map = {}
    for p in PRODUCTS:
        cur.execute(
            "INSERT INTO products (name, description, category, base_price) VALUES (?,?,?,?)",
            (p["name"], p["description"], p["category"], p["base_price"]),
        )
        pid = cur.lastrowid
        product_id_map[p["name"]] = pid
        for v in p["variants"]:
            cur.execute(
                "INSERT INTO product_variants (product_id, size, flavor, price, stock) VALUES (?,?,?,?,?)",
                (pid, v["size"], v["flavor"], v["price"], v["stock"]),
            )

    customer_ids = []
    for c in CUSTOMERS:
        cur.execute(
            "INSERT INTO customers (name, phone, email, address) VALUES (?,?,?,?)",
            (c["name"], c["phone"], c["email"], c["address"]),
        )
        customer_ids.append(cur.lastrowid)

    for cust_idx, items, status in SAMPLE_ORDERS:
        order_id = f"SN{uuid.uuid4().hex[:8].upper()}"
        total = 0.0
        resolved_items = []
        for pname, size, flavor, qty in items:
            pid = product_id_map[pname]
            row = cur.execute(
                "SELECT id, price FROM product_variants WHERE product_id=? AND size=? AND flavor=?",
                (pid, size, flavor),
            ).fetchone()
            if row:
                resolved_items.append((row["id"], qty, row["price"]))
                total += row["price"] * qty

        cur.execute(
            "INSERT INTO orders (id, customer_id, status, total_amount, delivery_address) VALUES (?,?,?,?,?)",
            (order_id, customer_ids[cust_idx], status, total,
             CUSTOMERS[cust_idx]["address"]),
        )
        for vid, qty, price in resolved_items:
            cur.execute(
                "INSERT INTO order_items (order_id, variant_id, quantity, unit_price) VALUES (?,?,?,?)",
                (order_id, vid, qty, price),
            )

    conn.commit()
    conn.close()
    print(f"SQLite seeded: {len(PRODUCTS)} products, {len(CUSTOMERS)} customers, {len(SAMPLE_ORDERS)} orders.")


def seed_chromadb():
    try:
        import chromadb
    except ImportError:
        print("chromadb not installed — skipping vector store seed.")
        return

    chroma_path = Path(__file__).parent.parent / "chroma_db"
    client = chromadb.PersistentClient(path=str(chroma_path))

    col = client.get_or_create_collection("spicenutrition_products")

    if col.count() > 0:
        print("ChromaDB already seeded — skipping.")
        return

    docs, metas, ids = [], [], []
    for i, p in enumerate(PRODUCTS):
        flavors = list({v["flavor"] for v in p["variants"]})
        sizes   = list({v["size"]   for v in p["variants"]})
        min_price = min(v["price"] for v in p["variants"])
        max_price = max(v["price"] for v in p["variants"])

        doc = (
            f"{p['name']}. {p['description']} "
            f"Category: {p['category']}. "
            f"Available sizes: {', '.join(sizes)}. "
            f"Available flavours: {', '.join(flavors)}. "
            f"Price: ₹{min_price:.0f}"
            + (f" – ₹{max_price:.0f}" if max_price != min_price else "") + "."
        )
        docs.append(doc)
        metas.append({
            "name":      p["name"],
            "category":  p["category"],
            "min_price": min_price,
            "max_price": max_price,
            "sizes":     ",".join(sizes),
            "flavors":   ",".join(flavors),
        })
        ids.append(f"product_{i}")

    kb_path = Path(__file__).parent.parent / "knowledge" / "spicenutrition.txt"
    if kb_path.exists():
        text = kb_path.read_text(encoding="utf-8")
        chunks = [c.strip() for c in text.split("\n\n") if len(c.strip()) > 80]
        for j, chunk in enumerate(chunks):
            docs.append(chunk)
            metas.append({"name": "knowledge", "category": "policy", "min_price": 0, "max_price": 0, "sizes": "", "flavors": ""})
            ids.append(f"kb_{j}")

    col.add(documents=docs, metadatas=metas, ids=ids)
    print(f"ChromaDB seeded: {len(PRODUCTS)} products + {len(ids) - len(PRODUCTS)} KB chunks.")


def seed_all():
    init_db()
    seed_sqlite()
    seed_chromadb()
    print("Seed complete.")


if __name__ == "__main__":
    seed_all()
