"""Register a Shopify order webhook pointing at a public callback URL (one-shot, live).

Usage: python register_webhook.py https://<tunnel>/webhooks/shopify/orders
Registers ORDERS_CREATE and ORDERS_UPDATED via the Admin GraphQL API.
"""
import sys

from dotenv import load_dotenv

MUTATION = """
mutation Create($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) {
    webhookSubscription { id }
    userErrors { field message }
  }
}
"""


def build_subscription_vars(callback_url, topic):
    return {"topic": topic, "sub": {"callbackUrl": callback_url, "format": "JSON"}}


def main():
    import os

    from extract.shopify_client import ShopifyClient

    if len(sys.argv) < 2:
        raise SystemExit("usage: python register_webhook.py <public-callback-url>")
    callback_url = sys.argv[1]

    load_dotenv()
    client = ShopifyClient(
        shop_domain=os.environ["SHOPIFY_SHOP_DOMAIN"],
        access_token=os.environ["SHOPIFY_ACCESS_TOKEN"],
    )
    for topic in ("ORDERS_CREATE", "ORDERS_UPDATED"):
        data = client.execute(MUTATION, build_subscription_vars(callback_url, topic))
        result = data["webhookSubscriptionCreate"]
        if result["userErrors"]:
            print(f"{topic}: FAILED -> {result['userErrors']}")
        else:
            print(f"{topic}: registered {result['webhookSubscription']['id']}")


if __name__ == "__main__":
    main()
