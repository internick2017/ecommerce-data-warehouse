"""Cursor-paginated extraction with optional updated_at watermark filter."""
from extract.queries import ENTITY_QUERIES


def extract_entity(client, entity, updated_since=None):
    query, root = ENTITY_QUERIES[entity]  # KeyError on unknown entity is intentional
    search = f"updated_at:>='{updated_since.isoformat()}'" if updated_since else None
    cursor = None
    while True:
        data = client.execute(query, {"cursor": cursor, "query": search})
        connection = data[root]
        for edge in connection["edges"]:
            yield edge["node"]
        page_info = connection["pageInfo"]
        if not page_info["hasNextPage"]:
            return
        cursor = page_info["endCursor"]
