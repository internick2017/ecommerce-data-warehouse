"""Seeds storeup.store with test orders via the Admin GraphQL orderCreate mutation.

The store has no sales yet; the dashboard needs history. Orders are tagged
'test-data' for later cleanup and processedAt is spread over the past 90 days.

Usage: python seed_shopify.py --count 60
Requires: app token with write_orders scope (and read_products).
"""
import argparse
import random
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

VARIANTS_QUERY = """
query Variants {
  productVariants(first: 50) {
    edges { node { id title price product { title } } }
  }
}
"""

ORDER_CREATE = """
mutation CreateTestOrder($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) {
    order { id name }
    userErrors { field message }
  }
}
"""


def spread_dates(n, days_back, now=None, seed=None):
    """n datetimes spread over the past days_back days, sorted ascending."""
    now = now or datetime.now(timezone.utc)
    rng = random.Random(seed)
    dates = [
        now - timedelta(days=rng.uniform(0, days_back),
                        hours=rng.uniform(0, 12))
        for _ in range(n)
    ]
    return sorted(dates)


def fetch_variants(client):
    data = client.execute(VARIANTS_QUERY)
    return [e["node"] for e in data["productVariants"]["edges"]]


def create_order(client, variants, processed_at, rng):
    chosen = rng.sample(variants, k=min(rng.randint(1, 3), len(variants)))
    line_items = [
        {"variantId": v["id"], "quantity": rng.randint(1, 3)} for v in chosen
    ]
    order_input = {
        "lineItems": line_items,
        "processedAt": processed_at.isoformat(),
        "financialStatus": "PAID",
        "tags": ["test-data"],
    }
    data = client.execute(ORDER_CREATE, {"order": order_input, "options": {}})
    result = data["orderCreate"]
    if result["userErrors"]:
        raise RuntimeError(f"orderCreate failed: {result['userErrors']}")
    return result["order"]["name"]


def main():
    import os

    from extract.shopify_client import ShopifyClient

    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--days-back", type=int, default=90)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    load_dotenv()
    client = ShopifyClient(
        shop_domain=os.environ["SHOPIFY_SHOP_DOMAIN"],
        access_token=os.environ["SHOPIFY_ACCESS_TOKEN"],
    )
    variants = fetch_variants(client)
    if not variants:
        raise SystemExit("No product variants in the store — add products first.")
    rng = random.Random(args.seed)
    dates = spread_dates(args.count, args.days_back, seed=args.seed)
    for i, processed_at in enumerate(dates, 1):
        name = create_order(client, variants, processed_at, rng)
        print(f"[{i}/{args.count}] created {name} @ {processed_at:%Y-%m-%d}")


if __name__ == "__main__":
    main()
