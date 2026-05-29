import asyncio
import sys
import tarfile
import types

libvirt_stub = types.SimpleNamespace(
    libvirtError=RuntimeError,
    open=lambda _uri: object(),
    VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE=0,
    VIR_KEYCODE_SET_LINUX=0,
)
sys.modules.pop("libvirt", None)
sys.modules["libvirt"] = libvirt_stub

from app.core.image_manager import ensure_image, normalize_source_spec


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


def test_normalize_source_spec_accepts_tar_xz_extract():
    spec = normalize_source_spec(
        {
            "url": "https://example.com/images/kali-linux-cloud-genericcloud-amd64.tar.xz",
            "extract": {
                "type": "tar.xz",
                "output_filename": "kali-linux-cloud-genericcloud-amd64.qcow2",
                "member_glob": "*.qcow2",
            },
        }
    )

    assert spec["filename"] == "kali-linux-cloud-genericcloud-amd64.tar.xz"
    assert spec["extract"]["type"] == "tar.xz"
    assert spec["extract"]["member_glob"] == "*.qcow2"


def test_ensure_image_extracts_tar_xz_archive(tmp_path, monkeypatch):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    archive_path = images_dir / "kali-linux-cloud-genericcloud-amd64.tar.xz"
    payload = b"qcow2-data"

    temp_member = tmp_path / "disk.qcow2"
    temp_member.write_bytes(payload)
    with tarfile.open(archive_path, mode="w:xz") as archive:
        archive.add(temp_member, arcname="disk.qcow2")

    monkeypatch.setattr("app.core.image_manager._images_dir", lambda: str(images_dir))

    result = asyncio.run(
        ensure_image(
            {
                "url": "https://example.com/images/kali-linux-cloud-genericcloud-amd64.tar.xz",
                "filename": archive_path.name,
                "extract": {
                    "type": "tar.xz",
                    "output_filename": "kali-linux-cloud-genericcloud-amd64.qcow2",
                    "member_glob": "*.qcow2",
                },
            }
        )
    )

    assert result.filename == "kali-linux-cloud-genericcloud-amd64.qcow2"
    assert (images_dir / result.filename).read_bytes() == payload