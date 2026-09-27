import re
import struct

from fastapi.testclient import TestClient

from candyconc.services.backend import server


SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _write_count_header(path, count: int) -> None:
    path.write_bytes(int(count).to_bytes(8, byteorder="little", signed=False))


def _write_lexicon_header(path, vocab_size: int) -> None:
    path.write_bytes(struct.pack("<4sIIIQQ", b"LEX2", 1, int(vocab_size), 0, 0, 0))


def _write_meta_manifest(index_path, fields=None, doc_count: int = 3) -> None:
    import json

    meta_dir = index_path / "meta_index"
    meta_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "doc_count": int(doc_count),
        "fields": fields
        if fields is not None
        else [
            {"name": "genre", "prefix": "f0", "has_str": True, "has_num": False},
            {"name": "year", "prefix": "f1", "has_str": False, "has_num": True},
        ],
    }
    (meta_dir / "meta_index.json").write_text(json.dumps(payload), encoding="utf-8")
    _write_lexicon_header(meta_dir / "f0.lex.bin", 12)
    _write_count_header(meta_dir / "f1.num_values.bin", doc_count)


def _fake_index(tmp_path, *, with_meta_index: bool = True):
    index_path = tmp_path / "fake_index"
    index_path.mkdir()
    (index_path / "meta.bin").write_bytes(b"\0")
    _write_count_header(index_path / "document_bounds.bin", 3)
    _write_count_header(index_path / "doc_metadata.idx.bin", 4)
    (index_path / "doc_metadata.mmap").write_bytes(b"metadata payload must not be decoded")
    (index_path / "doc_metadata.crc.bin").write_bytes(b"\0\0\0\0")
    if with_meta_index:
        _write_meta_manifest(index_path)
    return index_path


def _user_token(client: TestClient) -> str:
    return client.post("/api/v1/login", json={"username": "bob", "password": "bob"}).json()["token"]


def _raise_loaded(name: str):
    raise AssertionError(f"loaded {name}")


def test_analysis_meta_schema_requires_user_token_and_returns_structural_fingerprint(
    tmp_path,
    monkeypatch,
):
    index_path = _fake_index(tmp_path)
    monkeypatch.setattr(server, "_resolve_index_path", lambda: index_path)
    monkeypatch.setattr(server, "get_index", lambda: _raise_loaded("index"))
    monkeypatch.setattr(server, "get_corpus", lambda _corpus=None: _raise_loaded("corpus"))

    client = TestClient(server.app)
    unauth = client.get("/api/v1/analysis/meta_schema")
    assert unauth.status_code in {401, 403}

    response = client.get(
        "/api/v1/analysis/meta_schema",
        params={"token": _user_token(client)},
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["schemaVersion"] == 1
    assert data["corpus"] == "default"
    assert data["documentCount"] == 3
    assert SHA256_RE.match(data["indexFingerprint"])
    assert SHA256_RE.match(data["metadataSchemaHash"])
    assert data["fingerprint"] == data["indexFingerprint"]
    assert data["fingerprintStrength"] == "structural_index_artifacts"
    assert data["warnings"] == []
    assert data["docMetadataStore"] == {
        "available": True,
        "format": "mmap",
        "documentCount": 3,
        "crcAvailable": True,
    }
    assert data["metadataFields"] == [
        {
            "name": "genre",
            "kind": "string",
            "hasString": True,
            "hasNumber": False,
            "stringValueCount": 12,
            "numericValueCount": 0,
        },
        {
            "name": "year",
            "kind": "number",
            "hasString": False,
            "hasNumber": True,
            "stringValueCount": 0,
            "numericValueCount": 3,
        },
    ]
    for system_only_key in ("diskUsage", "tokenCount", "uptime", "cacheSize", "faissStatus"):
        assert system_only_key not in data


def test_analysis_meta_schema_fingerprint_is_stable_without_reading_metadata_blob(
    tmp_path,
    monkeypatch,
):
    index_path = _fake_index(tmp_path)
    monkeypatch.setattr(server, "_resolve_index_path", lambda: index_path)
    client = TestClient(server.app)
    token = _user_token(client)

    first = client.get("/api/v1/analysis/meta_schema", params={"token": token}).json()
    second = client.get("/api/v1/analysis/meta_schema", params={"token": token}).json()
    assert first["indexFingerprint"] == second["indexFingerprint"]
    assert first["metadataSchemaHash"] == second["metadataSchemaHash"]

    (index_path / "doc_metadata.mmap").write_bytes(b"changed raw metadata values")
    blob_changed = client.get("/api/v1/analysis/meta_schema", params={"token": token}).json()
    assert blob_changed["indexFingerprint"] == first["indexFingerprint"]
    assert blob_changed["metadataSchemaHash"] == first["metadataSchemaHash"]

    _write_meta_manifest(
        index_path,
        fields=[
            {"name": "genre", "prefix": "f0", "has_str": True, "has_num": False},
            {"name": "publication_year", "prefix": "f1", "has_str": False, "has_num": True},
        ],
    )
    schema_changed = client.get("/api/v1/analysis/meta_schema", params={"token": token}).json()
    assert schema_changed["indexFingerprint"] != first["indexFingerprint"]
    assert schema_changed["metadataSchemaHash"] != first["metadataSchemaHash"]


def test_analysis_meta_schema_handles_missing_meta_index_without_loading_corpus(
    tmp_path,
    monkeypatch,
):
    index_path = _fake_index(tmp_path, with_meta_index=False)
    monkeypatch.setattr(server, "_resolve_index_path", lambda: index_path)
    monkeypatch.setattr(server, "get_index", lambda: _raise_loaded("index"))
    monkeypatch.setattr(server, "get_corpus", lambda _corpus=None: _raise_loaded("corpus"))

    client = TestClient(server.app)
    response = client.get(
        "/api/v1/analysis/meta_schema",
        params={"token": _user_token(client)},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["metaIndex"]["available"] is False
    assert data["metadataFields"] == []
    assert data["warnings"] == ["meta_index manifest missing"]


def test_analysis_meta_schema_validates_named_corpus_without_loading_it(tmp_path, monkeypatch):
    corpora_dir = tmp_path / "corpora"
    corpora_dir.mkdir()
    monkeypatch.setattr(server, "_CORPUS_DIR", corpora_dir)
    monkeypatch.setattr(server, "get_index", lambda: _raise_loaded("index"))
    monkeypatch.setattr(server, "get_corpus", lambda _corpus=None: _raise_loaded("corpus"))

    client = TestClient(server.app)
    token = _user_token(client)

    invalid = client.get(
        "/api/v1/analysis/meta_schema",
        params={"token": token, "corpus": "../secret"},
    )
    assert invalid.status_code == 400

    missing = client.get(
        "/api/v1/analysis/meta_schema",
        params={"token": token, "corpus": "missing"},
    )
    assert missing.status_code == 404


def _write_lexicon(path, values: list[str]) -> None:
    """A LEX2 lexicon with its strings (core/index_format.py layout)."""
    blob = b"".join(v.encode("utf-8") for v in values)
    offsets = [0]
    position = 0
    for value in values:
        offsets.append(position)
        position += len(value.encode("utf-8"))
    freqs = [0] * (len(values) + 1)
    header = struct.pack("<4sIIIQQ", b"LEX2", 1, len(values), 0, 0, len(blob))
    path.write_bytes(
        header
        + struct.pack(f"<{len(offsets)}Q", *offsets)
        + struct.pack(f"<{len(freqs)}Q", *freqs)
        + blob
    )


def test_meta_schema_marks_builder_placeholders_of_an_unpaired_corpus(tmp_path, monkeypatch):
    # An unpaired import writes model=none, text_type=standalone and
    # variant=document into every document. The filter panel showed them as
    # filters with a single value.
    index_path = _fake_index(tmp_path, with_meta_index=False)
    fields = [
        {"name": "model", "prefix": "m", "has_str": True, "has_num": False},
        {"name": "text_type", "prefix": "t", "has_str": True, "has_num": False},
        {"name": "variant", "prefix": "v", "has_str": True, "has_num": False},
        {"name": "party", "prefix": "p", "has_str": True, "has_num": False},
    ]
    _write_meta_manifest(index_path, fields=fields)
    meta_dir = index_path / "meta_index"
    _write_lexicon(meta_dir / "m.lex.bin", ["none"])
    _write_lexicon(meta_dir / "t.lex.bin", ["standalone"])
    _write_lexicon(meta_dir / "v.lex.bin", ["document"])
    _write_lexicon(meta_dir / "p.lex.bin", ["Democratic", "Republican"])

    data = server._build_meta_schema_fingerprint(index_path, "sotu_en")
    marked = {f["name"] for f in data["metadataFields"] if f.get("placeholder")}
    assert marked == {"model", "text_type", "variant"}
    assert all("placeholder" not in f for f in data["metaIndex"]["fields"])

    # The mark does not change the fingerprints of the index.
    monkeypatch.setattr(server, "_meta_schema_placeholder_fields", lambda _path: set())
    unmarked = server._build_meta_schema_fingerprint(index_path, "sotu_en")
    assert unmarked["metadataSchemaHash"] == data["metadataSchemaHash"]
    assert unmarked["indexFingerprint"] == data["indexFingerprint"]


def test_meta_schema_keeps_real_values_in_placeholder_fields(tmp_path):
    index_path = _fake_index(tmp_path, with_meta_index=False)
    fields = [
        {"name": "model", "prefix": "m", "has_str": True, "has_num": False},
        {"name": "text_type", "prefix": "t", "has_str": True, "has_num": False},
    ]
    _write_meta_manifest(index_path, fields=fields)
    meta_dir = index_path / "meta_index"
    _write_lexicon(meta_dir / "m.lex.bin", ["easy"])
    _write_lexicon(meta_dir / "t.lex.bin", ["anchor", "version"])

    data = server._build_meta_schema_fingerprint(index_path, "paired_en")
    assert not [f for f in data["metadataFields"] if f.get("placeholder")]
