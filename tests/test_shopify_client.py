from unittest.mock import Mock

from app.shopify.client import fetch_shop_info, fetch_products_page


def _resp(json_data):
    resp = Mock(status_code=200)
    resp.json.return_value = json_data
    resp.raise_for_status = Mock()
    return resp


class TestFetchShopInfo:
    def test_parses_shop_identity(self, mocker):
        mock_post = mocker.patch(
            "app.shopify.client.httpx.post",
            return_value=_resp({
                "data": {"shop": {"name": "Test Store", "currencyCode": "PKR", "myshopifyDomain": "test-store.myshopify.com"}}
            }),
        )

        info = fetch_shop_info("test-store.myshopify.com", "shpat_abc123")

        assert info == {"name": "Test Store", "currency": "PKR", "domain": "test-store.myshopify.com"}
        sent = mock_post.call_args
        assert sent.kwargs["headers"]["X-Shopify-Access-Token"] == "shpat_abc123"
        assert "test-store.myshopify.com" in sent.args[0]

    def test_raises_on_graphql_errors(self, mocker):
        mocker.patch(
            "app.shopify.client.httpx.post",
            return_value=_resp({"errors": [{"message": "Invalid API key or access token"}]}),
        )
        try:
            fetch_shop_info("test-store.myshopify.com", "bad-token")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "Invalid API key" in str(e)


class TestFetchProductsPage:
    def test_parses_products_and_pagination(self, mocker):
        mocker.patch(
            "app.shopify.client.httpx.post",
            return_value=_resp({
                "data": {
                    "products": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor123"},
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/Product/111",
                                    "title": "Embroidered Kurta",
                                    "description": "Hand-embroidered cotton kurta.",
                                    "productType": "Kurta",
                                    "tags": ["new-arrival", "eid-collection"],
                                    "onlineStoreUrl": "https://test-store.myshopify.com/products/embroidered-kurta",
                                    "priceRangeV2": {"minVariantPrice": {"amount": "45.00", "currencyCode": "USD"}},
                                    "images": {"edges": [{"node": {"url": "https://cdn.shopify.com/img1.jpg"}}]},
                                }
                            }
                        ],
                    }
                }
            }),
        )

        page = fetch_products_page("test-store.myshopify.com", "shpat_abc123")

        assert page["has_next_page"] is True
        assert page["end_cursor"] == "cursor123"
        product = page["products"][0]
        assert product["shopify_product_id"] == "111"
        assert product["title"] == "Embroidered Kurta"
        assert product["tags"] == "new-arrival, eid-collection"
        assert product["price"] == "45.00"
        assert product["currency"] == "USD"
        assert product["image_urls"] == ["https://cdn.shopify.com/img1.jpg"]

    def test_handles_missing_optional_fields(self, mocker):
        mocker.patch(
            "app.shopify.client.httpx.post",
            return_value=_resp({
                "data": {
                    "products": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "edges": [
                            {
                                "node": {
                                    "id": "gid://shopify/Product/222",
                                    "title": "Unpublished Product",
                                    "description": None,
                                    "productType": None,
                                    "tags": [],
                                    "onlineStoreUrl": None,
                                    "priceRangeV2": None,
                                    "images": {"edges": []},
                                }
                            }
                        ],
                    }
                }
            }),
        )

        page = fetch_products_page("test-store.myshopify.com", "shpat_abc123")

        product = page["products"][0]
        assert product["description"] == ""
        assert product["tags"] == ""
        assert product["price"] is None
        assert product["image_urls"] == []
        assert page["has_next_page"] is False

    def test_created_after_builds_search_query_filter(self, mocker):
        mock_post = mocker.patch(
            "app.shopify.client.httpx.post",
            return_value=_resp({
                "data": {"products": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "edges": []}}
            }),
        )

        fetch_products_page("test-store.myshopify.com", "shpat_abc123", created_after="2026-04-30")

        sent_variables = mock_post.call_args.kwargs["json"]["variables"]
        assert sent_variables["query"] == "created_at:>='2026-04-30'"

    def test_no_created_after_sends_null_query_filter(self, mocker):
        mock_post = mocker.patch(
            "app.shopify.client.httpx.post",
            return_value=_resp({
                "data": {"products": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "edges": []}}
            }),
        )

        fetch_products_page("test-store.myshopify.com", "shpat_abc123")

        sent_variables = mock_post.call_args.kwargs["json"]["variables"]
        assert sent_variables["query"] is None


class TestGraphqlThrottleRetry:
    def test_retries_on_throttled_error_then_succeeds(self, mocker):
        throttled = _resp({"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]})
        success = _resp({"data": {"shop": {"name": "Test Store", "currencyCode": "USD", "myshopifyDomain": "test-store.myshopify.com"}}})
        mocker.patch("app.shopify.client.httpx.post", side_effect=[throttled, throttled, success])
        mock_sleep = mocker.patch("app.shopify.client.time.sleep")

        info = fetch_shop_info("test-store.myshopify.com", "shpat_abc123")

        assert info["name"] == "Test Store"
        assert mock_sleep.call_count == 2

    def test_gives_up_after_max_retries(self, mocker):
        throttled = _resp({"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]})
        mocker.patch("app.shopify.client.httpx.post", return_value=throttled)
        mocker.patch("app.shopify.client.time.sleep")

        try:
            fetch_shop_info("test-store.myshopify.com", "shpat_abc123")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "Throttled" in str(e)

    def test_non_throttled_error_fails_immediately_without_retry(self, mocker):
        error_resp = _resp({"errors": [{"message": "Invalid API key or access token"}]})
        mocker.patch("app.shopify.client.httpx.post", return_value=error_resp)
        mock_sleep = mocker.patch("app.shopify.client.time.sleep")

        try:
            fetch_shop_info("test-store.myshopify.com", "bad-token")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "Invalid API key" in str(e)
        mock_sleep.assert_not_called()
