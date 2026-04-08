import asyncio
import os
import tempfile
import importlib
import subprocess
import bz2
import gzip
import hashlib
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable
from urllib.parse import urlparse

import httpx

from app.core.vm_manager import WORK_DIR


def _images_dir() -> str:
    return os.path.join(WORK_DIR, "images")


@dataclass
class EnsureResult:
    filename: str
    container_path: str


_locks: Dict[str, asyncio.Lock] = {}


def _lock_for(filename: str) -> asyncio.Lock:
    if filename not in _locks:
        _locks[filename] = asyncio.Lock()
    return _locks[filename]


def _safe_filename(name: str) -> str:
    # Avoid path traversal
    return os.path.basename(name)


def _normalize_min_bytes(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"{field_name} must be >= 1")
    return parsed


def _normalize_sha256(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    digest = str(value).strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{field_name} must be a 64-character hex sha256 digest")
    return digest


def _allow_http_downloads() -> bool:
    return str(os.environ.get("CYBERANGE_ALLOW_HTTP_DOWNLOADS", "0")).strip().lower() in {"1", "true", "yes", "on"}


def normalize_source_spec(source: Any) -> Dict[str, Any]:
    if isinstance(source, str):
        raw: Dict[str, Any] = {"url": source}
    elif isinstance(source, dict):
        raw = dict(source)
    else:
        raise ValueError("invalid source type")

    url = str(raw.get("url") or "").strip()
    if not url:
        raise ValueError("source.url is required")

    parsed = urlparse(url)
    allowed_schemes = {"https", "http"} if _allow_http_downloads() else {"https"}
    if parsed.scheme.lower() not in allowed_schemes:
        allowed = ", ".join(sorted(allowed_schemes))
        raise ValueError(f"source.url must use one of: {allowed}")

    filename = _safe_filename(str(raw.get("filename") or os.path.basename(parsed.path) or "").strip())
    if not filename:
        raise ValueError("could not determine filename")

    normalized: Dict[str, Any] = {
        "url": url,
        "filename": filename,
        "min_bytes": _normalize_min_bytes(raw.get("min_bytes"), "min_bytes"),
        "sha256": _normalize_sha256(raw.get("sha256"), "sha256"),
        "archive_sha256": _normalize_sha256(raw.get("archive_sha256"), "archive_sha256"),
    }

    extract = raw.get("extract")
    if extract is not None:
        if not isinstance(extract, dict):
            raise ValueError("extract must be an object")
        extract_type = str(extract.get("type") or "").strip().lower()
        if extract_type not in {"7z", "bz2", "gz"}:
            raise ValueError(f"unsupported extract type: {extract_type}")
        output_filename = _safe_filename(str(extract.get("output_filename") or "").strip()) or None
        normalized["extract"] = {
            "type": extract_type,
            "output_filename": output_filename,
            "member_glob": extract.get("member_glob"),
            "remove_archive": bool(extract.get("remove_archive", False)),
            "min_bytes_output": _normalize_min_bytes(extract.get("min_bytes_output"), "extract.min_bytes_output"),
            "min_bytes_archive": _normalize_min_bytes(extract.get("min_bytes_archive"), "extract.min_bytes_archive"),
        }
    else:
        normalized["extract"] = None

    return normalized


def _file_matches_sha256(path: str, expected_sha256: Optional[str]) -> bool:
    if not expected_sha256:
        return True
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest() == expected_sha256


async def ensure_image(source: Any, progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None) -> EnsureResult:
    """Ensure an image/ISO exists in WORK_DIR/images.

    `source` can be:
      - {"url": "https://...", "filename": "foo.iso"}
      - {"url": "https://..."}  (filename derived from URL)
      - "https://..." (filename derived from URL)

    If the file already exists, it is not downloaded again.
    """

    normalized = normalize_source_spec(source)
    url = normalized["url"]
    filename = normalized["filename"]
    extract = normalized.get("extract")
    min_bytes = normalized.get("min_bytes")
    final_sha256 = normalized.get("sha256")
    archive_sha256 = normalized.get("archive_sha256")

    output_filename: Optional[str] = None
    extract_type: Optional[str] = None
    extract_member_glob: Optional[str] = None
    remove_archive: bool = False
    min_bytes_output: Optional[int] = None
    min_bytes_archive: Optional[int] = None

    if extract:
        extract_type = extract.get("type")
        output_filename = _safe_filename(extract.get("output_filename") or "") or None
        if not output_filename:
            # sensible default for Kali QEMU images
            if filename.lower().endswith(".7z"):
                output_filename = filename[:-3] + "qcow2"
            elif filename.lower().endswith(".bz2"):
                output_filename = filename[:-4]
            elif filename.lower().endswith(".gz"):
                output_filename = filename[:-3]
            else:
                raise ValueError("extract.output_filename is required")
        extract_member_glob = extract.get("member_glob")
        remove_archive = bool(extract.get("remove_archive", False))
        min_bytes_output = extract.get("min_bytes_output")
        min_bytes_archive = extract.get("min_bytes_archive")

    images_dir = _images_dir()
    os.makedirs(images_dir, exist_ok=True)

    # If extraction is requested, "final" refers to the extracted artifact.
    final_name = output_filename or filename
    final_path = os.path.join(images_dir, final_name)
    archive_path = os.path.join(images_dir, filename)

    required_final_bytes = int(min_bytes_output or min_bytes or 1)
    required_archive_bytes = int(min_bytes_archive or 1)

    lock = _lock_for(final_name)
    async with lock:
        if os.path.exists(final_path) and os.path.getsize(final_path) >= required_final_bytes and _file_matches_sha256(final_path, final_sha256):
            return EnsureResult(filename=final_name, container_path=final_path)

        if os.path.exists(final_path):
            try:
                os.remove(final_path)
            except OSError:
                pass

        if extract_type and os.path.exists(archive_path) and not _file_matches_sha256(archive_path, archive_sha256):
            try:
                os.remove(archive_path)
            except OSError:
                pass

        if extract_type and os.path.exists(archive_path) and os.path.getsize(archive_path) >= required_archive_bytes:
            tmp_path = None
        else:
            tmp_dir = images_dir
            fd, tmp_path = tempfile.mkstemp(prefix=f".{filename}.", dir=tmp_dir)
            os.close(fd)

        try:
            if tmp_path is not None:
                async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
                    async with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        total_size = int(resp.headers.get("content-length") or 0)
                        if progress_cb:
                            progress_cb(
                                {
                                    "type": "download_start",
                                    "url": url,
                                    "filename": filename,
                                    "final_name": final_name,
                                    "total": total_size,
                                }
                            )
                        with open(tmp_path, "wb") as f:
                            downloaded = 0
                            last_report_ts = 0.0
                            last_report_bytes = 0
                            async for chunk in resp.aiter_bytes():
                                f.write(chunk)
                                if progress_cb:
                                    downloaded += len(chunk)
                                    now = asyncio.get_event_loop().time()
                                    if (now - last_report_ts) >= 0.25 or (downloaded - last_report_bytes) >= (5 * 1024 * 1024):
                                        last_report_ts = now
                                        last_report_bytes = downloaded
                                        progress_cb(
                                            {
                                                "type": "download_progress",
                                                "url": url,
                                                "filename": filename,
                                                "final_name": final_name,
                                                "current": downloaded,
                                                "total": total_size,
                                            }
                                        )

                        if progress_cb:
                            size_on_disk = os.path.getsize(tmp_path)
                            progress_cb(
                                {
                                    "type": "download_complete",
                                    "url": url,
                                    "filename": filename,
                                    "final_name": final_name,
                                    "current": size_on_disk,
                                    "total": total_size,
                                }
                            )

                target_path = archive_path if extract_type else final_path
                if not extract_type and not _file_matches_sha256(tmp_path, final_sha256):
                    raise RuntimeError(f"downloaded file checksum mismatch for {final_name}")
                if extract_type and not _file_matches_sha256(tmp_path, archive_sha256):
                    raise RuntimeError(f"downloaded archive checksum mismatch for {filename}")

                os.replace(tmp_path, archive_path if extract_type else final_path)

                if not extract_type and os.path.getsize(final_path) < required_final_bytes:
                    raise RuntimeError(
                        f"downloaded file is smaller than expected: {final_name} ({os.path.getsize(final_path)} bytes < {required_final_bytes} bytes)"
                    )

                if not extract_type and not _file_matches_sha256(final_path, final_sha256):
                    raise RuntimeError(f"downloaded file checksum mismatch for {final_name}")

            if extract_type == "7z":
                # Lazy import so we don't require py7zr unless used.
                import shutil
                import fnmatch
                try:
                    py7zr = importlib.import_module("py7zr")
                except ModuleNotFoundError as e:
                    raise RuntimeError(
                        "py7zr is required to extract .7z images. Install it (pip install py7zr) "
                        "or rebuild the backend container after updating requirements."
                    ) from e

                if os.path.exists(final_path) and os.path.getsize(final_path) >= required_final_bytes and _file_matches_sha256(final_path, final_sha256):
                    return EnsureResult(filename=final_name, container_path=final_path)

                if not os.path.exists(archive_path) or os.path.getsize(archive_path) < required_archive_bytes:
                    raise RuntimeError("archive missing or smaller than expected; cannot extract")
                if not _file_matches_sha256(archive_path, archive_sha256):
                    raise RuntimeError(f"archive checksum mismatch for {filename}")

                extract_dir = tempfile.mkdtemp(prefix=f".extract.{final_name}.", dir=images_dir)
                try:
                    if progress_cb:
                        progress_cb(
                            {
                                "type": "extract_start",
                                "filename": filename,
                                "final_name": final_name,
                                "archive_path": archive_path,
                            }
                        )
                    seven_zip = shutil.which("7z") or shutil.which("7zz") or shutil.which("7zr")
                    if seven_zip:
                        # Use system 7z for maximum codec support.
                        proc = subprocess.run(
                            [seven_zip, "x", "-y", f"-o{extract_dir}", archive_path],
                            capture_output=True,
                            text=True,
                        )
                        if proc.returncode != 0:
                            raise RuntimeError(
                                f"7z extraction failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
                            )
                    else:
                        # Fallback to pure-python extraction.
                        with py7zr.SevenZipFile(archive_path, mode="r") as z:
                            z.extractall(path=extract_dir)

                    # Find the qcow2 to publish
                    chosen: Optional[str] = None
                    for root, _dirs, files in os.walk(extract_dir):
                        for file in files:
                            if extract_member_glob:
                                if fnmatch.fnmatch(file, extract_member_glob):
                                    chosen = os.path.join(root, file)
                                    break
                            else:
                                if file.lower().endswith(".qcow2"):
                                    chosen = os.path.join(root, file)
                                    break
                        if chosen:
                            break

                    if not chosen:
                        raise ValueError("extract failed: no matching file found in archive")

                    # Atomic-ish publish: copy then replace.
                    fd2, tmp_out = tempfile.mkstemp(prefix=f".{final_name}.", dir=images_dir)
                    os.close(fd2)
                    try:
                        shutil.copyfile(chosen, tmp_out)
                        os.replace(tmp_out, final_path)
                        if progress_cb:
                            progress_cb(
                                {
                                    "type": "extract_complete",
                                    "filename": filename,
                                    "final_name": final_name,
                                    "final_bytes": os.path.getsize(final_path) if os.path.exists(final_path) else 0,
                                }
                            )
                    except Exception:
                        try:
                            if os.path.exists(tmp_out):
                                os.remove(tmp_out)
                        finally:
                            raise

                finally:
                    shutil.rmtree(extract_dir, ignore_errors=True)

                if remove_archive:
                    try:
                        os.remove(archive_path)
                    except OSError:
                        pass

                if os.path.getsize(final_path) < required_final_bytes:
                    raise RuntimeError(
                        f"extracted file is smaller than expected: {final_name} ({os.path.getsize(final_path)} bytes < {required_final_bytes} bytes)"
                    )
                if not _file_matches_sha256(final_path, final_sha256):
                    raise RuntimeError(f"extracted file checksum mismatch for {final_name}")

                return EnsureResult(filename=final_name, container_path=final_path)

            if extract_type == "bz2":
                if os.path.exists(final_path) and os.path.getsize(final_path) >= required_final_bytes and _file_matches_sha256(final_path, final_sha256):
                    return EnsureResult(filename=final_name, container_path=final_path)

                if not os.path.exists(archive_path) or os.path.getsize(archive_path) < required_archive_bytes:
                    raise RuntimeError("archive missing or smaller than expected; cannot extract")
                if not _file_matches_sha256(archive_path, archive_sha256):
                    raise RuntimeError(f"archive checksum mismatch for {filename}")

                if progress_cb:
                    progress_cb(
                        {
                            "type": "extract_start",
                            "filename": filename,
                            "final_name": final_name,
                            "archive_path": archive_path,
                        }
                    )

                fd2, tmp_out = tempfile.mkstemp(prefix=f".{final_name}.", dir=images_dir)
                os.close(fd2)
                try:
                    with open(archive_path, "rb") as fin, open(tmp_out, "wb") as fout:
                        decomp = bz2.BZ2Decompressor()
                        while True:
                            chunk = fin.read(1024 * 1024)
                            if not chunk:
                                break
                            data = decomp.decompress(chunk)
                            if data:
                                fout.write(data)
                    os.replace(tmp_out, final_path)
                    if progress_cb:
                        progress_cb(
                            {
                                "type": "extract_complete",
                                "filename": filename,
                                "final_name": final_name,
                                "final_bytes": os.path.getsize(final_path) if os.path.exists(final_path) else 0,
                            }
                        )
                except Exception:
                    try:
                        if os.path.exists(tmp_out):
                            os.remove(tmp_out)
                    finally:
                        raise

                if remove_archive:
                    try:
                        os.remove(archive_path)
                    except OSError:
                        pass

                if os.path.getsize(final_path) < required_final_bytes:
                    raise RuntimeError(
                        f"extracted file is smaller than expected: {final_name} ({os.path.getsize(final_path)} bytes < {required_final_bytes} bytes)"
                    )
                if not _file_matches_sha256(final_path, final_sha256):
                    raise RuntimeError(f"extracted file checksum mismatch for {final_name}")

                return EnsureResult(filename=final_name, container_path=final_path)

            if extract_type == "gz":
                if os.path.exists(final_path) and os.path.getsize(final_path) >= required_final_bytes and _file_matches_sha256(final_path, final_sha256):
                    return EnsureResult(filename=final_name, container_path=final_path)

                if not os.path.exists(archive_path) or os.path.getsize(archive_path) < required_archive_bytes:
                    raise RuntimeError("archive missing or smaller than expected; cannot extract")
                if not _file_matches_sha256(archive_path, archive_sha256):
                    raise RuntimeError(f"archive checksum mismatch for {filename}")

                if progress_cb:
                    progress_cb(
                        {
                            "type": "extract_start",
                            "filename": filename,
                            "final_name": final_name,
                            "archive_path": archive_path,
                        }
                    )

                fd2, tmp_out = tempfile.mkstemp(prefix=f".{final_name}.", dir=images_dir)
                os.close(fd2)
                try:
                    with gzip.open(archive_path, "rb") as fin, open(tmp_out, "wb") as fout:
                        while True:
                            chunk = fin.read(1024 * 1024)
                            if not chunk:
                                break
                            fout.write(chunk)
                    os.replace(tmp_out, final_path)
                    if progress_cb:
                        progress_cb(
                            {
                                "type": "extract_complete",
                                "filename": filename,
                                "final_name": final_name,
                                "final_bytes": os.path.getsize(final_path) if os.path.exists(final_path) else 0,
                            }
                        )
                except Exception:
                    try:
                        if os.path.exists(tmp_out):
                            os.remove(tmp_out)
                    finally:
                        raise

                if remove_archive:
                    try:
                        os.remove(archive_path)
                    except OSError:
                        pass

                if os.path.getsize(final_path) < required_final_bytes:
                    raise RuntimeError(
                        f"extracted file is smaller than expected: {final_name} ({os.path.getsize(final_path)} bytes < {required_final_bytes} bytes)"
                    )
                if not _file_matches_sha256(final_path, final_sha256):
                    raise RuntimeError(f"extracted file checksum mismatch for {final_name}")

                return EnsureResult(filename=final_name, container_path=final_path)

            if not _file_matches_sha256(final_path, final_sha256):
                raise RuntimeError(f"downloaded file checksum mismatch for {final_name}")

            return EnsureResult(filename=final_name, container_path=final_path)
        except Exception:
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            finally:
                raise
