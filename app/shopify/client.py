"""Thin Shopify Admin GraphQL API client.

Built GraphQL-first, not against the REST Admin API: REST has been a
"legacy" API since Oct 2024, new custom apps are pushed toward GraphQL, and
Shopify's own guidance is that the REST/GraphQL feature gap only grows over
time — starting on REST in 2026 would mean migrating almost immediately.
"""
from typing import Optional
import httpx

_API_VERSION = "2026-04"  # Shopify ships a new version quarterly — bump periodically


def _url(shop_domain: str) -> str:
    return f"https://{shop_domain}/admin/api/{_API_VERSION}/graphql.json"


def _graphql(shop_domain: str, access_token: str, query: str, variables: Optional[dict] = None) -> dict:
    resp = httpx.post(
        _url(shop_domain),
        headers={"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"Shopify GraphQL error: {data['errors']}")
    return data["data"]


def fetch_shop_info(shop_domain: str, access_token: str) -> dict:
    """Cheap identity call — used to validate a token/domain on connect
    before anything is persisted."""
    query = "query { shop { name currencyCode myshopifyDomain } }"
    shop = _graphql(shop_domain, access_token, query)["shop"]
    return {"name": shop["name"], "currency": shop["currencyCode"], "domain": shop["myshopifyDomain"]}


_PRODUCTS_QUERY = """
query Products($first: Int!, $after: String) {
  products(first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        title
        description
        productType
        tags
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
                         page_size: int = 50) -> dict:
    data = _graphql(shop_domain, access_token, _PRODUCTS_QUERY, {"first": page_size, "after": cursor})
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
