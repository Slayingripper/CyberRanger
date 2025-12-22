import asyncio
import os
import tempfile
import importlib
import subprocess
import bz2
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable

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


async def ensure_image(source: Any, progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None) -> EnsureResult:
    """Ensure an image/ISO exists in WORK_DIR/images.

    `source` can be:
      - {"url": "https://...", "filename": "foo.iso"}
      - {"url": "https://..."}  (filename derived from URL)
      - "https://..." (filename derived from URL)

    If the file already exists, it is not downloaded again.
    """

    extract: Optional[Dict[str, Any]] = None
    min_bytes: Optional[int] = None

    if isinstance(source, str):
        url = source
        filename = os.path.basename(url.split("?")[0])
    elif isinstance(source, dict):
        url = source.get("url")
        if not url:
            raise ValueError("source.url is required")
        filename = source.get("filename") or os.path.basename(url.split("?")[0])
        extract = source.get("extract")
        min_bytes = source.get("min_bytes")
    else:
        raise ValueError("invalid source type")

    filename = _safe_filename(filename)
    if not filename:
        raise ValueError("could not determine filename")

    output_filename: Optional[str] = None
    extract_type: Optional[str] = None
    extract_member_glob: Optional[str] = None
    remove_archive: bool = False
    min_bytes_output: Optional[int] = None
    min_bytes_archive: Optional[int] = None

    if extract:
        extract_type = extract.get("type")
        if extract_type not in ("7z", "bz2"):
            raise ValueError(f"unsupported extract type: {extract_type}")
        output_filename = _safe_filename(extract.get("output_filename") or "") or None
        if not output_filename:
            # sensible default for Kali QEMU images
            if filename.lower().endswith(".7z"):
                output_filename = filename[:-3] + "qcow2"
            elif filename.lower().endswith(".bz2"):
                output_filename = filename[:-4]
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
        if os.path.exists(final_path) and os.path.getsize(final_path) >= required_final_bytes:
            return EnsureResult(filename=final_name, container_path=final_path)

        # If an existing artifact is present but too small, remove it so we can re-fetch.
        if os.path.exists(final_path):
            try:
                os.remove(final_path)
            except OSError:
                pass

        # If extraction is requested and we already have an archive, we can skip re-downloading.
        if extract_type and os.path.exists(archive_path) and os.path.getsize(archive_path) >= required_archive_bytes:
            tmp_path = None
        else:
            # Download to temp file then atomic rename.
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

                # Save download to either the final path (no extraction) or archive path (extraction)
                os.replace(tmp_path, archive_path if extract_type else final_path)

                if not extract_type and os.path.getsize(final_path) < required_final_bytes:
                    raise RuntimeError(
                        f"downloaded file is smaller than expected: {final_name} ({os.path.getsize(final_path)} bytes < {required_final_bytes} bytes)"
                    )

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

                if os.path.exists(final_path) and os.path.getsize(final_path) >= required_final_bytes:
                    return EnsureResult(filename=final_name, container_path=final_path)

                if not os.path.exists(archive_path) or os.path.getsize(archive_path) < required_archive_bytes:
                    raise RuntimeError("archive missing or smaller than expected; cannot extract")

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

                return EnsureResult(filename=final_name, container_path=final_path)

            if extract_type == "bz2":
                if os.path.exists(final_path) and os.path.getsize(final_path) >= required_final_bytes:
                    return EnsureResult(filename=final_name, container_path=final_path)

                if not os.path.exists(archive_path) or os.path.getsize(archive_path) < required_archive_bytes:
                    raise RuntimeError("archive missing or smaller than expected; cannot extract")

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

                return EnsureResult(filename=final_name, container_path=final_path)

            return EnsureResult(filename=final_name, container_path=final_path)
        except Exception:
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            finally:
                raise
