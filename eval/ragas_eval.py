"""
Quality evaluation for the Convrt sales agent.
Uses Claude itself as the judge (LLM-as-evaluator pattern).
Measures: faithfulness, answer relevance, tool use correctness, tone quality.

Run:  python -m eval.ragas_eval
"""
import sys
import json
import uuid
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import anthropic

from agent.graph import chat

# ── Test cases ────────────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "id": "tc_01",
        "category": "product_search",
        "user_message": "Hi! I want to build muscle. What protein do you recommend under ₹3000?",
        "expected_behaviors": [
            "searches products within budget",
            "suggests relevant protein products",
            "asks about goal or gives goal-based suggestion",
            "motivating tone",
        ],
    },
    {
        "id": "tc_02",
        "category": "inventory_check",
        "user_message": "Do you have Whey Protein Isolate in 1kg, Chocolate flavour?",
        "expected_behaviors": [
            "checks inventory using tool",
            "gives accurate stock count",
            "mentions price",
        ],
    },
    {
        "id": "tc_03",
        "category": "order_placement",
        "user_message": "I want to order Creatine Monohydrate, 250g, Unflavored. My address is 5 Park Street, Kolkata 700016.",
        "expected_behaviors": [
            "confirms order details before placing",
            "uses create_order tool",
            "provides order ID",
            "mentions delivery time",
        ],
    },
    {
        "id": "tc_04",
        "category": "order_tracking",
        "user_message": "Can you check my recent orders? My number is +919876543210.",
        "expected_behaviors": [
            "uses get_order_status tool",
            "lists orders with status",
            "helpful follow-up",
        ],
    },
    {
        "id": "tc_05",
        "category": "return_policy",
        "user_message": "What's your return policy if I already opened the tub?",
        "expected_behaviors": [
            "uses get_store_info tool",
            "mentions 30-day window and sealed/unopened condition",
            "explains process",
        ],
    },
    {
        "id": "tc_06",
        "category": "recommendation",
        "user_message": "I have a budget of ₹4000 and want a vegan muscle-building stack. What do you suggest?",
        "expected_behaviors": [
            "searches for vegan/plant protein and complementary products",
            "filters by budget",
            "gives specific product recommendations",
            "mentions sizes and flavours",
        ],
    },
    {
        "id": "tc_07",
        "category": "out_of_stock",
        "user_message": "I want the EAA Recovery in Mixed Berry. Is it available? If not add me to waitlist.",
        "expected_behaviors": [
            "checks inventory",
            "reports stock status",
            "offers or confirms waitlist option",
        ],
    },
    {
        "id": "tc_08",
        "category": "escalation_health",
        "user_message": "I felt dizzy and nauseous after taking your pre-workout. What's going on?",
        "expected_behaviors": [
            "shows empathy and concern",
            "advises stopping use and consulting a doctor",
            "uses escalate_to_human tool",
            "does NOT give a medical diagnosis",
        ],
    },
    {
        "id": "tc_09",
        "category": "website_link",
        "user_message": "Do you have a website where I can browse everything?",
        "expected_behaviors": [
            "uses get_website_link tool",
            "provides website URL",
            "encourages browsing",
        ],
    },
    {
        "id": "tc_10",
        "category": "dosage_guidance",
        "user_message": "When is the best time to take creatine, and do I need to load it?",
        "expected_behaviors": [
            "uses get_store_info / knowledge base",
            "gives accurate dosage guidance (3-5g daily, loading optional)",
            "does not overstate or give medical claims",
        ],
    },
]


# ── Evaluator ─────────────────────────────────────────────────────────────────

@dataclass
class EvalResult:
    test_id: str
    category: str
    user_message: str
    agent_response: str
    scores: dict = field(default_factory=dict)
    overall: float = 0.0
    feedback: str = ""


def evaluate_response(test_case: dict, agent_response: str, client: anthropic.Anthropic) -> EvalResult:
    """Use Claude to judge the agent response on 4 dimensions."""

    judge_prompt = f"""You are evaluating a WhatsApp sales assistant for an Indian sports nutrition & supplement store called SpiceNutrition.

## Test Case
Category: {test_case['category']}
User message: "{test_case['user_message']}"
Expected behaviors: {json.dumps(test_case['expected_behaviors'], indent=2)}

## Agent Response
{agent_response}

## Task
Score the agent response on these 4 dimensions (0.0 to 1.0 each):

1. **relevance** — Does the response directly address what the user asked?
2. **faithfulness** — Is the information accurate and grounded (no hallucinated prices/products)?
3. **tool_use** — Did the agent likely use the correct tools (infer from response content)?
4. **tone** — Is the response warm, friendly, WhatsApp-appropriate, and concise?

Respond ONLY with valid JSON in this exact format:
{{
  "relevance": 0.0,
  "faithfulness": 0.0,
  "tool_use": 0.0,
  "tone": 0.0,
  "feedback": "one sentence summary of strengths and weaknesses"
}}"""

    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=300,
        messages=[{"role": "user", "content": judge_prompt}],
    )

    try:
        raw = response.content[0].text.strip()
        # Extract JSON block if wrapped in markdown
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        data = json.loads(raw)
        scores = {k: float(data.get(k, 0)) for k in ["relevance", "faithfulness", "tool_use", "tone"]}
        overall = sum(scores.values()) / len(scores)
        feedback = data.get("feedback", "")
    except Exception as e:
        scores = {"relevance": 0, "faithfulness": 0, "tool_use": 0, "tone": 0}
        overall = 0.0
        feedback = f"Evaluation parse error: {e}"

    return EvalResult(
        test_id=test_case["id"],
        category=test_case["category"],
        user_message=test_case["user_message"],
        agent_response=agent_response,
        scores=scores,
        overall=overall,
        feedback=feedback,
    )


def run_evaluation(test_cases: list[dict] = None) -> list[EvalResult]:
    test_cases = test_cases or TEST_CASES
    client = anthropic.Anthropic()
    results = []

    print(f"\n{'='*60}")
    print(f"  Convrt Agent Evaluation — {len(test_cases)} test cases")
    print(f"{'='*60}\n")

    for tc in test_cases:
        session_id = str(uuid.uuid4())
        print(f"[{tc['id']}] {tc['category']}: {tc['user_message'][:60]}...")

        try:
            agent_response = chat(tc["user_message"], session_id)
        except Exception as e:
            agent_response = f"[ERROR: {e}]"

        result = evaluate_response(tc, agent_response, client)
        results.append(result)

        scores_str = " | ".join(f"{k}: {v:.2f}" for k, v in result.scores.items())
        print(f"  Scores: {scores_str}")
        print(f"  Overall: {result.overall:.2f}")
        print(f"  Feedback: {result.feedback}\n")

    # Summary
    avg_overall = sum(r.overall for r in results) / len(results)
    avg_by_category: dict[str, list[float]] = {}
    for r in results:
        avg_by_category.setdefault(r.category, []).append(r.overall)

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Average overall score: {avg_overall:.2f} / 1.00")
    print(f"\n  By category:")
    for cat, scores in sorted(avg_by_category.items()):
        print(f"    {cat:<25} {sum(scores)/len(scores):.2f}")

    # Dimension averages
    dims = ["relevance", "faithfulness", "tool_use", "tone"]
    print(f"\n  By dimension:")
    for dim in dims:
        avg = sum(r.scores.get(dim, 0) for r in results) / len(results)
        bar = "█" * int(avg * 20)
        print(f"    {dim:<15} {avg:.2f}  {bar}")

    print(f"\n{'='*60}\n")
    return results


def save_results(results: list[EvalResult], path: str = "eval/results.json"):
    out = []
    for r in results:
        out.append({
            "test_id":       r.test_id,
            "category":      r.category,
            "user_message":  r.user_message,
            "agent_response": r.agent_response,
            "scores":        r.scores,
            "overall":       r.overall,
            "feedback":      r.feedback,
        })
    Path(path).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Results saved to {path}")


if __name__ == "__main__":
    results = run_evaluation()
    save_results(results)
