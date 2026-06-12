"""Shopify Admin GraphQL client with bounded retries and throttle handling."""
import random
import time

import requests

API_VERSION = "2025-01"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ShopifyError(Exception):
    pass


class ShopifyClient:
    def __init__(self, shop_domain, access_token, session=None,
                 max_retries=5, sleep=time.sleep):
        self.url = f"https://{shop_domain}/admin/api/{API_VERSION}/graphql.json"
        self.headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.sleep = sleep

    def execute(self, query, variables=None):
        attempt = 0
        while True:
            resp = self.session.post(
                self.url,
                json={"query": query, "variables": variables or {}},
                headers=self.headers,
                timeout=30,
            )
            if resp.status_code in RETRYABLE_STATUS:
                attempt = self._backoff_or_raise(attempt, f"HTTP {resp.status_code}")
                continue
            resp.raise_for_status()
            body = resp.json()
            errors = body.get("errors")
            if errors:
                if any(e.get("extensions", {}).get("code") == "THROTTLED" for e in errors):
                    attempt = self._backoff_or_raise(attempt, "THROTTLED")
                    continue
                raise ShopifyError(f"GraphQL errors: {errors}")
            return body["data"]

    def _backoff_or_raise(self, attempt, reason):
        attempt += 1
        if attempt > self.max_retries:
            raise ShopifyError(f"Gave up after {self.max_retries} retries ({reason})")
        self.sleep(min(2 ** attempt + random.random(), 30))
        return attempt
