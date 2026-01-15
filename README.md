# CyberRange ANU

A lightweight, scalable Cyber Range platform using QEMU/KVM and a modern web interface.

> **📚 [Complete Documentation Available in the Wiki](docs/wiki/Home.md)**

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
- **Images**: Place images under `./images` (bind-mounted to `/app/images` in the backend). Scenarios can also auto-download images via `scenario.sources`.
- **Frontend API URL**: `VITE_API_URL` (default: `http://localhost:8001/api`).
- **Range Mapper**: set `RANGE_MAPPER_ENABLE=1` to allow scans.
- **OpenWrt Auto-Download (optional)**:
   - `OPENWRT_IMAGE_URL` (e.g. OpenWrt x86_64 `*.img.gz`)
   - `OPENWRT_IMAGE_FILENAME` (download filename)
   - `OPENWRT_IMAGE_OUTPUT` (extracted image name, default `openwrt.img`)

## Documentation

Comprehensive documentation is available in the [Wiki](docs/wiki/):

- **[📖 Wiki Home](docs/wiki/Home.md)** - Introduction and overview
- **[🚀 Installation & Setup](docs/wiki/Installation-and-Setup.md)** - Detailed installation guide
- **[📚 User Guide](docs/wiki/User-Guide.md)** - Complete user documentation
- **[🏗️ Architecture](docs/wiki/Architecture.md)** - Technical architecture details
- **[🔌 API Reference](docs/wiki/API-Reference.md)** - REST API documentation
- **[🎓 Training System](docs/wiki/Training-System.md)** - Creating training courses
- **[🌐 Topology Builder](docs/wiki/Topology-Builder.md)** - Network scenario design
- **[🔧 Troubleshooting](docs/wiki/Troubleshooting.md)** - Common issues and solutions
- **[🤝 Contributing](docs/wiki/Contributing.md)** - Contribution guidelines

## Troubleshooting
- **Permission Denied**: If the backend cannot connect to libvirt, ensure the socket permissions are correct or run docker-compose with `sudo`.
- **NoVNC**: Ensure ports 6080-6100 are available.
- **WebSocket Errors**: If you see “Unsupported upgrade request,” ensure the backend image was rebuilt after updating dependencies.
