"""Generates a post idea (hook/caption/cta/hashtags) for a real Shopify
product — the product-grounded counterpart to content_strategist.py's
trend-grounded idea generation. Same LLM provider pattern (Qwen-max primary,
Claude Haiku fallback), same "one prompt-building/parsing path" shape, but
fed a real product's title/description/price/type/tags instead of a trend
cluster, since the whole point of the Shopify feature is content grounded in
an actual, real, purchasable item rather than a generic trend riff.
"""
import json
import logging
import os

logger = logging.getLogger("culturix.shopify.content_ideas")


def _get_qwen_client():
    from openai import OpenAI
    return OpenAI(
        api_key=os.environ["QWEN_API_KEY"],
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )


def _get_claude_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _build_prompt(product: dict) -> str:
    price_line = f"{product.get('price')} {product.get('currency')}" if product.get("price") else "unknown"
    return f"""You are a social media content strategist for a clothing brand.

Write ONE Instagram/TikTok post proposal for this real product, to be posted
alongside its actual product photo:

Title: {product.get('title', '')}
Description: {product.get('description', '') or '(no description provided)'}
Product type: {product.get('product_type', '') or 'unknown'}
Tags: {product.get('tags', '') or 'none'}
Price: {price_line}

The post must be about this exact product — name it specifically, don't write
generic filler like "this piece" or "our latest drop" without saying what it
actually is. Write in a trendy, authentic tone suited to a fashion brand's
Instagram/TikTok, not a generic e-commerce product description.

Return ONLY valid JSON with exactly these keys:
- hook: attention-grabbing opening line for the post/reel (max 15 words)
- caption: full post caption with 3-5 relevant hashtags woven in naturally (40-80 words)
- cta: clear call to action, e.g. "Shop the link in bio" (max 10 words)
- hashtag_strategy: exactly 5 hashtags mixing broad fashion reach + niche/product-specific, space-separated
- platform: best single platform for this specific product post ("Instagram", "TikTok", or "Pinterest")

Return ONLY the JSON object, no other text."""


def _parse_idea(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def generate_product_post_idea(product: dict) -> dict:
    """product is the dict shape returned by shopify/service.py's
    list_products() (title/description/product_type/tags/price/currency)."""
    prompt = _build_prompt(product)
    if os.getenv("QWEN_API_KEY"):
        qwen = _get_qwen_client()
        response = qwen.chat.completions.create(
            model="qwen-max",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        raw = response.choices[0].message.content
    else:
        client = _get_claude_client()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text

    return _parse_idea(raw)
