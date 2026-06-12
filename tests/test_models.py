from load.models import validate_record


VALID_ORDER = {
    "id": "gid://shopify/Order/1",
    "name": "#1001",
    "createdAt": "2026-06-01T10:00:00Z",
    "processedAt": "2026-06-01T10:00:00Z",
    "updatedAt": "2026-06-01T10:00:00Z",
    "currencyCode": "EUR",
    "totalPriceSet": {"shopMoney": {"amount": "49.90"}},
    "subtotalPriceSet": {"shopMoney": {"amount": "41.24"}},
    "customer": {"id": "gid://shopify/Customer/7"},
    "lineItems": {"edges": []},
}


def test_valid_order_passes():
    ok, reason = validate_record("orders", VALID_ORDER)
    assert ok is True
    assert reason is None


def test_order_missing_total_is_rejected_with_reason():
    bad = {k: v for k, v in VALID_ORDER.items() if k != "totalPriceSet"}
    ok, reason = validate_record("orders", bad)
    assert ok is False
    assert "totalPriceSet" in reason


def test_order_with_null_customer_passes():
    guest = dict(VALID_ORDER, customer=None)
    ok, _ = validate_record("orders", guest)
    assert ok is True


def test_valid_product_passes():
    ok, _ = validate_record("products", {
        "id": "gid://shopify/Product/9",
        "title": "Mug",
        "status": "ACTIVE",
        "vendor": "storeup",
        "productType": "Kitchen",
        "createdAt": "2026-05-01T00:00:00Z",
        "updatedAt": "2026-05-01T00:00:00Z",
        "variants": {"edges": []},
    })
    assert ok is True


def test_valid_customer_passes():
    ok, _ = validate_record("customers", {
        "id": "gid://shopify/Customer/7",
        "displayName": "Test Buyer",
        "numberOfOrders": "3",
        "createdAt": "2026-05-01T00:00:00Z",
        "updatedAt": "2026-05-01T00:00:00Z",
    })
    assert ok is True


def test_garbage_is_rejected_not_raised():
    ok, reason = validate_record("orders", {"hello": "world"})
    assert ok is False
    assert reason
