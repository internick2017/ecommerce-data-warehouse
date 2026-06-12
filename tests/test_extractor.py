from datetime import datetime, timezone

from extract.extractor import extract_entity


class FakeClient:
    """Scripted client: returns one response per execute() call, records variables."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def execute(self, query, variables=None):
        self.calls.append(variables)
        return self.pages.pop(0)


def page(root, nodes, has_next, cursor=None):
    return {root: {
        "edges": [{"node": n} for n in nodes],
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
    }}


def test_paginates_until_has_next_page_false():
    client = FakeClient([
        page("orders", [{"id": "gid://1"}, {"id": "gid://2"}], True, "c1"),
        page("orders", [{"id": "gid://3"}], False),
    ])
    records = list(extract_entity(client, "orders"))
    assert [r["id"] for r in records] == ["gid://1", "gid://2", "gid://3"]
    assert client.calls[0]["cursor"] is None
    assert client.calls[1]["cursor"] == "c1"


def test_incremental_passes_updated_at_filter():
    client = FakeClient([page("orders", [], False)])
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    list(extract_entity(client, "orders", updated_since=since))
    assert client.calls[0]["query"] == "updated_at:>='2026-06-01T00:00:00+00:00'"


def test_full_extract_passes_null_filter():
    client = FakeClient([page("products", [], False)])
    list(extract_entity(client, "products"))
    assert client.calls[0]["query"] is None


def test_unknown_entity_raises():
    import pytest
    with pytest.raises(KeyError):
        list(extract_entity(FakeClient([]), "invoices"))
