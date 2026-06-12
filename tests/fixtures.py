"""Realistic raw payload fixtures shared by transform tests."""
from datetime import datetime, timezone

from load import pg_loader

NOW = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)


def order(n, customer_gid, total, items, processed="2026-06-01T10:00:00Z"):
    return {
        "id": f"gid://shopify/Order/{n}",
        "name": f"#10{n:02d}",
        "createdAt": processed,
        "processedAt": processed,
        "updatedAt": processed,
        "currencyCode": "EUR",
        "totalPriceSet": {"shopMoney": {"amount": str(total)}},
        "subtotalPriceSet": {"shopMoney": {"amount": str(total)}},
        "customer": {"id": customer_gid} if customer_gid else None,
        "lineItems": {"edges": [{"node": i} for i in items]},
    }


def item(n, product_gid, qty, unit_price):
    return {
        "id": f"gid://shopify/LineItem/{n}",
        "title": f"Item {n}",
        "quantity": qty,
        "sku": f"SKU-{n}",
        "product": {"id": product_gid},
        "originalUnitPriceSet": {"shopMoney": {"amount": str(unit_price)}},
    }


def product(n, title="Mug"):
    return {
        "id": f"gid://shopify/Product/{n}",
        "title": title,
        "status": "ACTIVE",
        "vendor": "storeup",
        "productType": "Kitchen",
        "createdAt": "2026-05-01T00:00:00Z",
        "updatedAt": "2026-05-01T00:00:00Z",
        "variants": {"edges": []},
    }


def customer(n, name="Test Buyer"):
    return {
        "id": f"gid://shopify/Customer/{n}",
        "displayName": name,
        "numberOfOrders": "1",
        "createdAt": "2026-05-01T00:00:00Z",
        "updatedAt": "2026-05-01T00:00:00Z",
    }


def seed_raw(db):
    """Two products, two customers, three orders (one is a guest order)."""
    pg_loader.upsert_raw(db, "products", [product(1, "Mug"), product(2, "Tee")],
                         load_id=1, extracted_at=NOW)
    pg_loader.upsert_raw(db, "customers", [customer(1, "Ana"), customer(2, "Luis")],
                         load_id=1, extracted_at=NOW)
    pg_loader.upsert_raw(db, "orders", [
        order(1, "gid://shopify/Customer/1", "30.00",
              [item(1, "gid://shopify/Product/1", 2, "15.00")],
              processed="2026-06-01T10:00:00Z"),
        order(2, "gid://shopify/Customer/1", "20.00",
              [item(2, "gid://shopify/Product/2", 1, "20.00")],
              processed="2026-06-05T10:00:00Z"),
        order(3, None, "15.00",
              [item(3, "gid://shopify/Product/1", 1, "15.00")],
              processed="2026-06-08T10:00:00Z"),
    ], load_id=1, extracted_at=NOW)
