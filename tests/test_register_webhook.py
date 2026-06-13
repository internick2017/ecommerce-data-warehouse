from register_webhook import build_subscription_vars


def test_build_subscription_vars():
    vars_ = build_subscription_vars("https://x.example/webhooks/shopify/orders", "ORDERS_CREATE")
    assert vars_["topic"] == "ORDERS_CREATE"
    assert vars_["sub"]["callbackUrl"] == "https://x.example/webhooks/shopify/orders"
    assert vars_["sub"]["format"] == "JSON"
