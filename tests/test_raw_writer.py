import json

from load.raw_writer import LocalRawWriter, S3RawWriter, writer_from_env


def test_local_writer_writes_jsonl(tmp_path):
    w = LocalRawWriter(base_dir=tmp_path)
    uri = w.write("orders", [{"id": "1"}, {"id": "2"}], load_id=7)
    files = list(tmp_path.rglob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0]) == {"id": "1"}
    assert "orders" in uri and "load_7" in uri


def test_local_writer_empty_records_writes_nothing(tmp_path):
    w = LocalRawWriter(base_dir=tmp_path)
    uri = w.write("orders", [], load_id=7)
    assert uri is None
    assert list(tmp_path.rglob("*")) == []


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, Bucket, Key, Body):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})


def test_s3_writer_puts_jsonl_object():
    s3 = FakeS3()
    w = S3RawWriter(bucket="my-bucket", client=s3)
    uri = w.write("orders", [{"id": "1"}], load_id=3)
    put = s3.puts[0]
    assert put["Bucket"] == "my-bucket"
    assert put["Key"].startswith("raw/orders/")
    assert put["Key"].endswith("load_3.jsonl")
    assert json.loads(put["Body"].decode("utf-8").strip()) == {"id": "1"}
    assert uri == f"s3://my-bucket/{put['Key']}"


def test_writer_from_env_prefers_s3(monkeypatch, tmp_path):
    monkeypatch.setenv("S3_BUCKET", "")
    w = writer_from_env(local_base=tmp_path)
    assert isinstance(w, LocalRawWriter)
