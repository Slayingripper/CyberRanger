#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGES_DIR="$ROOT_DIR/images"

mkdir -p "$IMAGES_DIR"

have() { command -v "$1" >/dev/null 2>&1; }

verify_sha256() {
  local file="$1"
  local expected="$2"

  if [[ -z "$expected" ]]; then
    echo "[info] no sha256 provided for $(basename "$file"), skipping verification"
    return 0
  fi

  if ! [[ -f "$file" ]]; then
    echo "[error] file not found: $file" >&2
    return 1
  fi

  local actual
  if have sha256sum; then
    actual=$(sha256sum "$file" | awk '{print $1}')
  elif have shasum; then
    actual=$(shasum -a 256 "$file" | awk '{print $1}')
  else
    echo "[warn] no sha256sum or shasum available, skipping verification" >&2
    return 0
  fi

  if [[ "$actual" != "$expected" ]]; then
    echo "[FAIL] sha256 mismatch for $(basename "$file")" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
    rm -f "$file"
    return 1
  fi

  echo "[ok] sha256 verified: $(basename "$file")"
  return 0
}

download() {
  local url="$1"
  local out="$2"

  if [[ -f "$out" ]]; then
    echo "[skip] $(basename "$out") already exists"
    return 0
  fi

  if have curl; then
    echo "[curl] $url -> $out"
    curl -L --fail --progress-bar "$url" -o "$out"
  elif have wget; then
    echo "[wget] $url -> $out"
    wget -O "$out" "$url"
  else
    echo "Need curl or wget to download files" >&2
    exit 1
  fi
}

extract_bz2() {
  local in_bz2="$1"
  local out_file="$2"

  if [[ -f "$out_file" ]]; then
    echo "[skip] $(basename "$out_file") already exists"
    return 0
  fi

  if have bunzip2; then
    echo "[bunzip2] $in_bz2 -> $out_file"
    # bunzip2 writes to stdout with -c
    bunzip2 -c "$in_bz2" > "$out_file"
  elif have python3; then
    echo "[python3] $in_bz2 -> $out_file"
    python3 - <<PY
import bz2
import shutil

src = r"$in_bz2"
dst = r"$out_file"
with bz2.open(src, 'rb') as fin, open(dst, 'wb') as fout:
    shutil.copyfileobj(fin, fout, length=1024*1024)
PY
  else
    echo "Need bunzip2 or python3 to extract .bz2" >&2
    exit 1
  fi
}

echo "Images dir: $IMAGES_DIR"

echo "\n== Ubuntu 20.04 cloud image =="
# Official Ubuntu cloud image URL (focal)
UBUNTU_URL="https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img"
UBUNTU_SHA256="18f2977d77dfea1b74aee14533bd21c34f789139e949c57023b7364894b7e5e9"
download "$UBUNTU_URL" "$IMAGES_DIR/focal-server-cloudimg-amd64.img"
verify_sha256 "$IMAGES_DIR/focal-server-cloudimg-amd64.img" "$UBUNTU_SHA256"

echo "\n== Cirros (tiny test image) =="
CIRROS_URL="https://download.cirros-cloud.net/0.6.2/cirros-0.6.2-x86_64-disk.img"
download "$CIRROS_URL" "$IMAGES_DIR/cirros.img"

echo "\n== Kali (auto via .7z or manual) =="
KALI_7Z_URL="https://cdimage.kali.org/current/kali-linux-2026.1-qemu-amd64.7z"
KALI_7Z_SHA256="efce2da10c775da5f58954166f633d5da9115e29663731dcb65d616f19d966f4"
KALI_7Z="$IMAGES_DIR/kali-linux-2026.1-qemu-amd64.7z"
KALI_QCOW2="$IMAGES_DIR/kali-linux-2026.1-qemu-amd64.qcow2"

if [[ -f "$KALI_QCOW2" ]]; then
  echo "[skip] $(basename "$KALI_QCOW2") already exists"
elif [[ "${KALI_SKIP:-}" == "1" ]]; then
  echo "[info] KALI_SKIP=1; skipping Kali download"
else
  download "$KALI_7Z_URL" "$KALI_7Z"
  verify_sha256 "$KALI_7Z" "$KALI_7Z_SHA256"
  if have 7z; then
    echo "[7z] extracting $KALI_7Z"
    7z x -y -o"$IMAGES_DIR" "$KALI_7Z"
  elif have 7zz; then
    echo "[7zz] extracting $KALI_7Z"
    7zz x -y -o"$IMAGES_DIR" "$KALI_7Z"
  elif have python3; then
    echo "[py7zr] extracting $KALI_7Z"
    python3 -c "import py7zr; py7zr.SevenZipFile(r'$KALI_7Z','r').extractall(r'$IMAGES_DIR')"
  else
    echo "[warn] Need 7z, 7zz, or python3+py7zr to extract .7z. Skipping Kali extraction." >&2
  fi
fi

echo "\n== OPNsense 25.7 (auto) =="
OPNSENSE_URL="https://pkg.opnsense.org/releases/25.7/OPNsense-25.7-vga-amd64.img.bz2"
OPNSENSE_BZ2="$IMAGES_DIR/OPNsense-25.7-vga-amd64.img.bz2"
OPNSENSE_IMG="$IMAGES_DIR/opnsense.img"
download "$OPNSENSE_URL" "$OPNSENSE_BZ2"
extract_bz2 "$OPNSENSE_BZ2" "$OPNSENSE_IMG"

echo "\n== Windows 10 (manual) =="
cat <<'EOF'
Windows images cannot be downloaded automatically here.
Provide your own qcow2 base image and place it at:
  images/windows10.qcow2

Alternatives:
- Use the ISO-based install flow: set image to a .iso in your topology and add
  automation.steps to drive the installer via send_text/send_key.
- Replace the Victim node image with ubuntu-20.04 for a fully automated demo.
EOF

echo "\nDone. Current images:" 
ls -lh "$IMAGES_DIR" | sed -n '1,200p'
