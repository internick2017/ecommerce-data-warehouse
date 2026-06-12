"""Raw layer writers: JSONL to S3 (data-lake staging) or local dir fallback."""
import json
import os
from datetime import date
from pathlib import Path


def _jsonl(records):
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"


class LocalRawWriter:
    def __init__(self, base_dir="data/raw_local"):
        self.base_dir = Path(base_dir)

    def write(self, entity, records, load_id):
        if not records:
            return None
        target = self.base_dir / entity / date.today().isoformat()
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"load_{load_id}.jsonl"
        path.write_text(_jsonl(records), encoding="utf-8")
        return str(path)


class S3RawWriter:
    def __init__(self, bucket, client=None):
        self.bucket = bucket
        if client is None:
            import boto3
            client = boto3.client("s3")
        self.client = client

    def write(self, entity, records, load_id):
        if not records:
            return None
        key = f"raw/{entity}/{date.today().isoformat()}/load_{load_id}.jsonl"
        self.client.put_object(
            Bucket=self.bucket, Key=key,
            Body=_jsonl(records).encode("utf-8"),
        )
        return f"s3://{self.bucket}/{key}"


def writer_from_env(local_base="data/raw_local"):
    bucket = os.environ.get("S3_BUCKET", "").strip()
    if bucket:
        return S3RawWriter(bucket=bucket)
    return LocalRawWriter(base_dir=local_base)
