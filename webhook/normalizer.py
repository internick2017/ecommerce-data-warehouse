"""Map a Shopify webhook order payload (REST shape) to the canonical record shape.

The canonical shape matches what extract.extractor yields and what
load.models.OrderRecord + transform/sql/010_staging.sql consume, so the rest of
the pipeline handles webhook-sourced orders identically to API-extracted ones.
"""


def _gid(kind, numeric_id):
    return f"gid://shopify/{kind}/{numeric_id}"


def _money(amount):
    return {"shopMoney": {"amount": amount}}


def _line_item_node(item):
    li_gid = item.get("admin_graphql_api_id") or _gid("LineItem", item.get("id"))
    product = None
    if item.get("product_id") is not None:
        product = {"id": _gid("Product", item["product_id"])}
    return {
        "id": li_gid,
        "title": item.get("title"),
        "quantity": item.get("quantity"),
        "sku": item.get("sku"),
        "product": product,
        "originalUnitPriceSet": _money(item.get("price")),
    }


def webhook_order_to_record(payload):
    order_gid = payload.get("admin_graphql_api_id") or _gid("Order", payload.get("id"))

    customer = payload.get("customer")
    if customer:
        customer_gid = customer.get("admin_graphql_api_id") or _gid("Customer", customer.get("id"))
        customer_ref = {"id": customer_gid}
    else:
        customer_ref = None

    edges = [{"node": _line_item_node(li)} for li in payload.get("line_items", [])]

    return {
        "id": order_gid,
        "name": payload.get("name"),
        "createdAt": payload.get("created_at"),
        "processedAt": payload.get("processed_at"),
        "updatedAt": payload.get("updated_at"),
        "currencyCode": payload.get("currency"),
        "totalPriceSet": _money(payload.get("total_price")),
        "subtotalPriceSet": _money(payload.get("subtotal_price")),
        "customer": customer_ref,
        "lineItems": {"edges": edges},
    }
