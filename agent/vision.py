"""
Vision: identify a supplement product from an uploaded image
(e.g. a screenshot from an Instagram/▶️ reel) using Groq's multimodal
Llama 4 Scout model. Returns a short text description that the text
agent then matches against the SpiceNutrition catalogue.
"""
import os
import base64

VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

_PROMPT = (
    "You are a product identifier for a sports-nutrition store. The image is likely a "
    "screenshot from a social-media reel or a product photo. In 1-2 short sentences, describe "
    "the SUPPLEMENT product you see: its type (whey protein, plant protein, mass gainer, "
    "creatine, pre-workout, BCAA/EAA, multivitamin, omega-3, etc.), the flavour if visible, the "
    "size/form (powder tub, capsules, etc.), and any brand text you can read. "
    "If it is clearly NOT a supplement, say so briefly. Do not make up details you cannot see."
)


def describe_product_image(image_bytes: bytes, mime: str = "image/jpeg", caption: str = "") -> str:
    """Send the image to the Groq vision model and return a short description."""
    if not image_bytes:
        return ""
    try:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        b64 = base64.b64encode(image_bytes).decode()
        data_uri = f"data:{mime};base64,{b64}"
        text = _PROMPT + (f"\nCustomer's note: {caption}" if caption else "")
        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }],
            temperature=0.2,
            max_tokens=300,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"__VISION_ERROR__: {e}"


def guess_mime(filename: str) -> str:
    fn = (filename or "").lower()
    if fn.endswith(".png"):
        return "image/png"
    if fn.endswith(".webp"):
        return "image/webp"
    if fn.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"
