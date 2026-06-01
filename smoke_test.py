"""Quick smoke test — run from convrt directory."""
import sys
import io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# Load .env so the LLM provider key is detected (same as app.py / api)
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("1. Testing database init...")
from database.models import init_db, get_connection, rows_to_list
init_db()
conn = get_connection()
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(f"   Tables: {tables}")
conn.close()
assert len(tables) >= 7, "Expected 7 tables"

print("2. Testing seed data...")
from database.seed_data import seed_all
seed_all()

conn = get_connection()
product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
customer_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
order_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
variant_count = conn.execute("SELECT COUNT(*) FROM product_variants").fetchone()[0]
conn.close()
print(f"   Products: {product_count}, Customers: {customer_count}, Orders: {order_count}, Variants: {variant_count}")
assert product_count == 15
assert customer_count == 3
assert order_count == 5

print("3. Testing tool imports...")
from agent.tools import get_tools, check_inventory, search_products
tools = get_tools()
print(f"   Tools loaded: {[t.name for t in tools]}")
assert len(tools) == 9

print("4. Testing tools directly (no LLM)...")
result = check_inventory.invoke({"product_name": "Whey Protein Isolate", "size": "1kg", "flavor": "Chocolate"})
print(f"   check_inventory: {result[:80]}...")
assert "Whey Protein Isolate" in result

result2 = search_products.invoke({"query": "vegan protein for muscle gain", "budget_max": 3000.0})
print(f"   search_products: {result2[:80]}...")

print("5. Testing LLM provider detection...")
import os
from agent.nodes import _build_llm, _load_config
provider_keys = {
    "gemini": os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
    "groq": os.getenv("GROQ_API_KEY"),
    "anthropic": os.getenv("ANTHROPIC_API_KEY"),
}
active = os.getenv("LLM_PROVIDER") or next((k for k, v in provider_keys.items() if v), "NONE")
print(f"   Active provider: {active}")
llm = _build_llm(_load_config())
print(f"   LLM built: {type(llm).__name__}")

print("6. Testing graph import...")
from agent.graph import get_graph
graph = get_graph()
print(f"   Graph compiled: {graph}")

print("7. Testing rate limiter (anti-spam)...")
from agent.rate_limiter import check_rate_limit, reset, PER_MINUTE
reset("+910000000000")
allowed_count = 0
for _ in range(PER_MINUTE + 5):
    ok, _msg = check_rate_limit("+910000000000")
    if ok:
        allowed_count += 1
print(f"   Allowed {allowed_count}/{PER_MINUTE + 5} (limit {PER_MINUTE}/min) — extras got canned reply")
assert allowed_count == PER_MINUTE, f"Expected {PER_MINUTE} allowed, got {allowed_count}"
reset()

print("\n✅ All smoke tests passed!")
