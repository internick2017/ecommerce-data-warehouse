from webhook.normalizer import webhook_order_to_record

WEBHOOK_ORDER = {
    "id": 820982911946154500,
    "admin_graphql_api_id": "gid://shopify/Order/820982911946154508",
    "name": "#1001",
    "created_at": "2026-06-01T10:00:00-04:00",
    "processed_at": "2026-06-01T10:00:00-04:00",
    "updated_at": "2026-06-01T10:05:00-04:00",
    "currency": "EUR",
    "total_price": "49.90",
    "subtotal_price": "41.24",
    "customer": {
        "id": 115310627314723950,
        "admin_graphql_api_id": "gid://shopify/Customer/115310627314723954",
    },
    "line_items": [
        {
            "id": 866550311766439000,
            "admin_graphql_api_id": "gid://shopify/LineItem/866550311766439020",
            "title": "Mug",
            "quantity": 2,
            "sku": "SKU-1",
            "price": "15.00",
            "product_id": 632910392,
        }
    ],
}


def test_maps_order_top_level_fields():
    rec = webhook_order_to_record(WEBHOOK_ORDER)
    assert rec["id"] == "gid://shopify/Order/820982911946154508"
    assert rec["name"] == "#1001"
    assert rec["currencyCode"] == "EUR"
    assert rec["totalPriceSet"]["shopMoney"]["amount"] == "49.90"
    assert rec["subtotalPriceSet"]["shopMoney"]["amount"] == "41.24"
    assert rec["processedAt"] == "2026-06-01T10:00:00-04:00"


def test_maps_customer_gid():
    rec = webhook_order_to_record(WEBHOOK_ORDER)
    assert rec["customer"] == {"id": "gid://shopify/Customer/115310627314723954"}


def test_guest_order_has_null_customer():
    guest = dict(WEBHOOK_ORDER, customer=None)
    rec = webhook_order_to_record(guest)
    assert rec["customer"] is None


def test_maps_line_items_to_edges():
    rec = webhook_order_to_record(WEBHOOK_ORDER)
    edges = rec["lineItems"]["edges"]
    assert len(edges) == 1
    node = edges[0]["node"]
    assert node["id"] == "gid://shopify/LineItem/866550311766439020"
    assert node["quantity"] == 2
    assert node["sku"] == "SKU-1"
    assert node["product"]["id"] == "gid://shopify/Product/632910392"
    assert node["originalUnitPriceSet"]["shopMoney"]["amount"] == "15.00"


def test_builds_gid_when_admin_graphql_api_id_absent():
    minimal = {k: v for k, v in WEBHOOK_ORDER.items() if k != "admin_graphql_api_id"}
    rec = webhook_order_to_record(minimal)
    assert rec["id"] == "gid://shopify/Order/820982911946154500"


def test_normalized_record_passes_validation():
    from load.models import validate_record
    rec = webhook_order_to_record(WEBHOOK_ORDER)
    ok, reason = validate_record("orders", rec)
    assert ok is True, reason
