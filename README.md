# CyberRange ANU

A lightweight, scalable Cyber Range platform using QEMU/KVM and a modern web interface.

## Features
- **Backend**: Python FastAPI with Libvirt integration.
- **Frontend**: React + Vite with Tailwind CSS.
- **Console Access**: NoVNC integration for browser-based VM access.
- **Scenarios**: YAML-based scenario definition.

## Prerequisites
- Linux Host (Ubuntu/Debian recommended)
- Docker & Docker Compose
- KVM/QEMU installed on the host (`sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils`)
- Current user in `libvirt` and `kvm` groups (`sudo usermod -aG libvirt,kvm $USER`)

## Quick Start

1. **Clone the repository**
   ```bash
   git clone <repo_url>
   cd CyberangeANU
   ```

2. **Start the platform**
   ```bash
   docker-compose up --build
   ```

3. **Access the Interface**
   Open your browser and navigate to:
   [http://localhost:5173](http://localhost:5173)

## Configuration
- **Scenarios**: Add new scenarios in the `scenarios/` directory.
- **Images**: Ensure QCOW2 images are available in the path specified in your scenarios (default `/var/lib/libvirt/images/`).

## Troubleshooting
- **Permission Denied**: If the backend cannot connect to libvirt, ensure the socket permissions are correct or run docker-compose with `sudo`.
- **NoVNC**: Ensure ports 6080-6100 are available.
