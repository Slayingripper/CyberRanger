from app.core.image_manager import normalize_source_spec


def test_normalize_source_spec_rejects_http_by_default(monkeypatch):
    monkeypatch.delenv("CYBERANGE_ALLOW_HTTP_DOWNLOADS", raising=False)
    try:
        normalize_source_spec({"url": "http://example.com/test.iso", "filename": "test.iso"})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "source.url must use one of" in str(exc)


def test_normalize_source_spec_accepts_https_extract_and_checksums():
    spec = normalize_source_spec(
        {
            "url": "https://example.com/images/test.iso.gz",
            "extract": {
                "type": "gz",
                "output_filename": "test.iso",
                "min_bytes_output": 1024,
                "remove_archive": True,
            },
            "sha256": "a" * 64,
            "archive_sha256": "b" * 64,
        }
    )

    assert spec["filename"] == "test.iso.gz"
    assert spec["extract"]["output_filename"] == "test.iso"
    assert spec["extract"]["remove_archive"] is True
    assert spec["sha256"] == "a" * 64
    assert spec["archive_sha256"] == "b" * 64