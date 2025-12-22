#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGES_DIR="$ROOT_DIR/images"

mkdir -p "$IMAGES_DIR"

have() { command -v "$1" >/dev/null 2>&1; }

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
download "$UBUNTU_URL" "$IMAGES_DIR/ubuntu-20.04-server-cloudimg-amd64.img"

echo "\n== Cirros (tiny test image) =="
CIRROS_URL="https://download.cirros-cloud.net/0.6.2/cirros-0.6.2-x86_64-disk.img"
download "$CIRROS_URL" "$IMAGES_DIR/cirros.img"

echo "\n== Kali (manual/optional) =="
cat <<'EOF'
Kali images are large. If you want the script to download Kali automatically,
set KALI_QCOW2_URL to an official direct-download URL, e.g. a cdimage.kali.org link,
then re-run this script.

Example:
  export KALI_QCOW2_URL="https://cdimage.kali.org/kali-YYYY.X/kali-linux-YYYY.X-qemu-amd64.qcow2"
EOF

if [[ "${KALI_QCOW2_URL:-}" != "" ]]; then
  download "$KALI_QCOW2_URL" "$IMAGES_DIR/kali-linux-2023.3-qemu-amd64.qcow2"
else
  echo "[info] KALI_QCOW2_URL not set; skipping Kali download"
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
- Use an ISO-based install flow (not wired into the topology deploy yet)
- Replace the Victim node image with ubuntu-20.04 for a fully automated demo
EOF

echo "\nDone. Current images:" 
ls -lh "$IMAGES_DIR" | sed -n '1,200p'
