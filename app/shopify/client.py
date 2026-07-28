"""Thin Shopify Admin GraphQL API client.

Built GraphQL-first, not against the REST Admin API: REST has been a
"legacy" API since Oct 2024, new custom apps are pushed toward GraphQL, and
Shopify's own guidance is that the REST/GraphQL feature gap only grows over
time — starting on REST in 2026 would mean migrating almost immediately.
"""
import time
from typing import Optional
import httpx

_API_VERSION = "2026-04"  # Shopify ships a new version quarterly — bump periodically
_MAX_THROTTLE_RETRIES = 5
_THROTTLE_BACKOFF_SECONDS = 2  # doubles each retry: 2, 4, 8, 16, 32


def _url(shop_domain: str) -> str:
    return f"https://{shop_domain}/admin/api/{_API_VERSION}/graphql.json"


def _graphql(shop_domain: str, access_token: str, query: str, variables: Optional[dict] = None) -> dict:
    """Shopify's GraphQL Admin API uses cost-based throttling (a leaky
    bucket, not a simple request-count limit) — a large catalog sync can
    burn through the bucket well before pagination finishes, live-confirmed
    against a real store with a large product catalog. Retries with backoff
    on a THROTTLED error rather than failing the whole sync partway through."""
    for attempt in range(_MAX_THROTTLE_RETRIES + 1):
        resp = httpx.post(
            _url(shop_domain),
            headers={"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"},
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        errors = data.get("errors")
        if not errors:
            return data["data"]
        is_throttled = any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors)
        if not is_throttled or attempt == _MAX_THROTTLE_RETRIES:
            raise RuntimeError(f"Shopify GraphQL error: {errors}")
        time.sleep(_THROTTLE_BACKOFF_SECONDS * (2 ** attempt))
    raise RuntimeError("unreachable")  # loop always returns or raises above


def fetch_shop_info(shop_domain: str, access_token: str) -> dict:
    """Cheap identity call — used to validate a token/domain on connect
    before anything is persisted."""
    query = "query { shop { name currencyCode myshopifyDomain } }"
    shop = _graphql(shop_domain, access_token, query)["shop"]
    return {"name": shop["name"], "currency": shop["currencyCode"], "domain": shop["myshopifyDomain"]}


_PRODUCTS_QUERY = """
query Products($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        description
        productType
        tags
        createdAt
        onlineStoreUrl
        priceRangeV2 { minVariantPrice { amount currencyCode } }
        images(first: 10) { edges { node { url } } }
      }
    }
  }
}
"""


def _gid_to_id(gid: str) -> str:
    """'gid://shopify/Product/123456789' -> '123456789'."""
    return gid.rsplit("/", 1)[-1]


def fetch_products_page(shop_domain: str, access_token: str, cursor: Optional[str] = None,
                         page_size: int = 50, created_after: Optional[str] = None) -> dict:
    """`created_after` is an ISO date/datetime string (e.g. "2026-04-30"),
    passed through as a Shopify search-query filter (`created_at:>=...`) so
    a large catalog only pages through recently-created products rather
    than the entire store history — see Shopify's search syntax docs."""
    search_query = f"created_at:>='{created_after}'" if created_after else None
    data = _graphql(
        shop_domain, access_token, _PRODUCTS_QUERY,
        {"first": page_size, "after": cursor, "query": search_query},
    )
    connection = data["products"]

    products = []
    for edge in connection["edges"]:
        node = edge["node"]
        min_price = (node.get("priceRangeV2") or {}).get("minVariantPrice") or {}
        products.append({
            "shopify_product_id": _gid_to_id(node["id"]),
            "title": node["title"],
            "description": node.get("description") or "",
            "product_type": node.get("productType") or "",
            "tags": ", ".join(node.get("tags") or []),
            "created_at": node.get("createdAt"),
            "price": min_price.get("amount"),
            "currency": min_price.get("currencyCode"),
            "product_url": node.get("onlineStoreUrl"),
            "image_urls": [e["node"]["url"] for e in ((node.get("images") or {}).get("edges") or [])],
        })

    page_info = connection["pageInfo"]
    return {
        "products": products,
        "has_next_page": page_info["hasNextPage"],
        "end_cursor": page_info["endCursor"],
    }
