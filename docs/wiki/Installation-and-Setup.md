# Installation & Setup

This guide will help you install and configure CyberRanger on your system.

## Prerequisites

### System Requirements

- **Operating System**: Linux (Ubuntu/Debian recommended)
- **CPU**: x86_64 with virtualization support (Intel VT-x or AMD-V)
- **RAM**: Minimum 8GB (16GB+ recommended for multiple VMs)
- **Storage**: 50GB+ free disk space
- **Network**: Internet connection for downloading images

### Required Software

1. **Docker & Docker Compose**
   ```bash
   # Install Docker
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   
   # Install Docker Compose
   sudo apt-get update
   sudo apt-get install docker-compose-plugin
   ```

2. **KVM/QEMU and Libvirt**
   ```bash
   sudo apt update
   sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils
   ```

3. **User Permissions**
   Add your user to the required groups:
   ```bash
   sudo usermod -aG libvirt,kvm $USER
   ```
   
   **Important**: Log out and log back in for group changes to take effect.

### Verify Virtualization Support

Check if your CPU supports virtualization:
```bash
egrep -c '(vmx|svm)' /proc/cpuinfo
```
If the output is greater than 0, virtualization is supported.

Verify KVM installation:
```bash
sudo kvm-ok
```

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/Slayingripper/CyberRanger.git
cd CyberRanger
```

### 2. Create Required Directories

```bash
mkdir -p images disks scenarios
```

### 3. Configure Environment Variables

The platform uses environment variables defined in `docker-compose.yml`. You can customize:

- `VITE_API_URL`: Frontend API endpoint (default: `http://localhost:8001/api`)
- `RANGE_MAPPER_ENABLE`: Enable network range mapping (set to `1`)
- `OPENWRT_IMAGE_URL`: URL for OpenWrt image auto-download
- `OPENWRT_IMAGE_FILENAME`: Downloaded filename
- `OPENWRT_IMAGE_OUTPUT`: Extracted image name

### 4. Start the Platform

```bash
docker-compose up --build
```

This will:
- Build the backend and frontend Docker containers
- Start the FastAPI backend on port 8001
- Start the Vite development server on port 5173
- Mount necessary volumes for VM management

### 5. Access the Web Interface

Open your browser and navigate to:
```
http://localhost:5173
```

You should see the CyberRanger dashboard!

## Initial Setup

### 1. Verify Libvirt Connection

Check that the backend can connect to libvirt:
```bash
docker logs cyberrange-backend
```

Look for successful connection messages. If you see permission errors, see [Troubleshooting](Troubleshooting.md).

### 2. Download Base Images

Place VM images in the `./images` directory or use the image management interface.

#### Option A: Manual Download
```bash
cd images

# Ubuntu 20.04 Cloud Image
wget https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img

# Kali Linux (example)
# Download from https://www.kali.org/get-kali/#kali-virtual-machines
```

#### Option B: Use Setup Script
```bash
./scripts/setup_images.sh
```

#### Option C: Use Web Interface
Navigate to the "Images" tab in the web interface to download images directly.

### 3. Test VM Creation

1. Go to the Dashboard
2. Click "Create New VM"
3. Configure a test VM:
   - Name: `test-vm`
   - Memory: 2048 MB
   - vCPUs: 2
   - Select an image
4. Click "Create VM"

If successful, you should see the VM in your dashboard!

## Directory Structure

After installation, your directory structure should look like:

```
CyberRanger/
├── backend/           # FastAPI backend application
│   ├── app/          # Application code
│   ├── data/         # Runtime data
│   ├── docs/         # Backend documentation
│   ├── tests/        # Unit tests
│   └── trainings/    # Training definitions
├── frontend/         # React frontend application
│   └── src/         # Source code
├── scenarios/        # YAML scenario definitions
├── images/          # VM disk images (ISOs, qcow2)
├── disks/           # VM runtime disks
├── docs/            # Documentation
└── scripts/         # Utility scripts
```

## Docker Configuration

### Ports Used

- **8001**: Backend API (FastAPI)
- **5173**: Frontend (Vite dev server)
- **6080-6100**: NoVNC WebSocket ports for VM consoles

### Volume Mounts

- `/var/run/libvirt/libvirt-sock`: Libvirt socket for VM management
- `./backend:/app`: Backend code (hot reload)
- `./frontend:/app`: Frontend code (hot reload)
- `./scenarios:/app/scenarios`: Scenario definitions
- `./images:/app/images`: VM images
- `./disks:/app/disks`: VM runtime disks

## Production Deployment

For production use:

1. **Build Frontend**
   ```bash
   cd frontend
   npm run build
   ```

2. **Use Production Web Server**
   Serve the built frontend with Nginx or Apache instead of Vite dev server.

3. **Configure Reverse Proxy**
   Set up a reverse proxy (Nginx) for the backend API.

4. **Enable HTTPS**
   Use Let's Encrypt or another certificate authority.

5. **Restrict NoVNC Access**
   Configure firewall rules to limit NoVNC port access.

6. **Update Environment Variables**
   Set production values for API URLs and disable debug modes.

## Next Steps

- Read the [User Guide](User-Guide.md) to learn how to use CyberRanger
- Explore the [Topology Builder](Topology-Builder.md) to create custom network scenarios
- Check out the [Training System](Training-System.md) to build training courses
- Review [Troubleshooting](Troubleshooting.md) if you encounter issues

## Updating CyberRanger

To update to the latest version:

```bash
cd CyberRanger
git pull origin main
docker-compose down
docker-compose up --build
```
