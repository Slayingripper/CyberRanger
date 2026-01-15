# User Guide

This guide covers the main features and workflows in CyberRanger.

## Table of Contents

- [Dashboard Overview](#dashboard-overview)
- [Managing Virtual Machines](#managing-virtual-machines)
- [Image Management](#image-management)
- [Topology Builder](#topology-builder)
- [Training System](#training-system)
- [Settings](#settings)

## Dashboard Overview

The Dashboard is your main control center for managing virtual machines.

### Navigation

The sidebar provides access to:
- 🖥️ **Dashboard**: VM overview and management
- 💿 **Images**: Manage VM images and ISOs
- 🌐 **Topology Builder**: Design network scenarios
- 📚 **Training**: Create and run training courses
- ⚙️ **Settings**: Configure platform settings

### VM Cards

Each VM is displayed as a card showing:
- **Name**: Virtual machine identifier
- **Status**: Running (green) or Stopped (red)
- **Memory**: Allocated RAM in MB
- **vCPUs**: Number of virtual CPUs
- **VNC Port**: Port for console access

## Managing Virtual Machines

### Creating a VM

1. Click the **"+ Create New VM"** card on the Dashboard
2. Fill in the VM details:
   - **VM Name**: Unique identifier for your VM
   - **Memory (MB)**: RAM allocation (e.g., 2048 for 2GB)
   - **vCPUs**: Number of CPU cores (1-4 recommended)
   - **Boot Image**: Select an ISO or disk image
3. (Optional) Enable **Cloud-Init Configuration**:
   - Set username and password
   - Add packages to install (comma-separated)
   - Packages will be installed on first boot
4. Click **"Create VM"**

### Starting a VM

1. Find the VM card on the Dashboard
2. Click the green **"Start"** button
3. Wait for the status to change to "Running"
4. The VNC port will be displayed once running

### Stopping a VM

1. Locate the running VM
2. Click the yellow **"Stop"** button
3. The VM will gracefully shut down

### Accessing the Console

1. Ensure the VM is running
2. Click **"Open Console (NoVNC)"** on the VM card
3. A new window opens with the VM console
4. Interact with the VM directly in your browser

**Console Features:**
- Full keyboard and mouse support
- Clipboard integration
- Fullscreen mode
- Connection status indicator

### Deleting a VM

⚠️ **Warning**: This action cannot be undone!

1. Click **"Delete"** on the VM card
2. Confirm deletion in the popup
3. The VM and its disk will be permanently removed

## Image Management

The Images page helps you manage OS images and installation ISOs.

### Viewing Available Images

Navigate to the **Images** tab to see:
- Image name
- File path
- File size
- Format (ISO, qcow2, img)

### Uploading Images

**Method 1: Direct Upload**
1. Click **"Upload Image"**
2. Select a file from your computer
3. Wait for upload to complete

**Method 2: Download from URL**
1. Click **"Download from URL"**
2. Enter the image URL
3. Specify the output filename
4. Click **"Download"**

**Method 3: Manual Copy**
```bash
# Copy images to the images directory
cp /path/to/image.iso ./images/
```

### Supported Image Formats

- **ISO**: Installation media (`.iso`)
- **QCOW2**: QEMU disk images (`.qcow2`)
- **Raw Images**: Raw disk images (`.img`)

### Pre-configured Image Keys

CyberRanger recognizes these image shortcuts:
- `kali-linux`: Kali Linux images
- `ubuntu-20.04`: Ubuntu 20.04 cloud images
- `windows-10`: Windows 10 images
- `openwrt`: OpenWrt router images
- `opnsense`: OPNsense firewall images
- `security-onion`: Security Onion IDS/IPS

## Topology Builder

Create complex network scenarios with the visual topology builder.

### Creating a Topology

1. Go to **Topology Builder**
2. Drag nodes from the palette onto the canvas
3. Configure each node:
   - **Label**: Display name
   - **Image**: OS image to use
   - **CPU**: Number of vCPUs
   - **RAM**: Memory in MB
   - **Assets**: Packages and scripts to install
4. Connect nodes by dragging between them
5. Click **"Deploy Topology"**

### Node Configuration

**Basic Settings:**
- Label: How the VM appears in the topology
- Image: Which OS to boot

**Resources:**
- CPU: 1-8 vCPUs
- RAM: 512-8192 MB

**Assets (Automated Setup):**
- **Packages**: Software to install (e.g., `nmap`, `wireshark`)
- **Commands**: Shell commands to run on boot
- **Ansible Playbooks**: Complex configuration automation

### Network Design

- **Connected Nodes**: Nodes connected with edges share a network
- **Isolated Components**: Disconnected groups get separate networks
- **OPNsense Integration**: Automatically configures WAN/LAN when present
- **NAT Networks**: Each component gets its own NAT network

### Deploying Scenarios

Two deployment methods:

**Synchronous Deploy:**
- Click "Deploy Topology"
- Wait for all VMs to be created
- Returns results immediately

**Asynchronous Deploy (Job-based):**
- Click "Deploy as Job"
- Monitor progress in real-time
- Download images automatically
- Track per-node status

### Scenario Configuration

Define scenarios with metadata:
- **Name**: Scenario identifier
- **Team**: Target team (Red/Blue/Purple)
- **Objective**: Training goal
- **Difficulty**: Easy/Medium/Hard
- **Sources**: Auto-download URLs for images

### Example: Basic Pentest Scenario

1. Add two nodes:
   - **Attacker**: Kali Linux (2 CPU, 2048 MB)
   - **Target**: Metasploitable (1 CPU, 1024 MB)
2. Connect them with an edge
3. Configure attacker assets:
   - Packages: `nmap,metasploit-framework`
4. Deploy the topology
5. Access consoles and begin testing

## Training System

Build structured cybersecurity training courses.

### Training Structure

**Training** → **Levels** → **Tasks**

- **Training**: Complete course (e.g., "Web Security Fundamentals")
- **Level**: Individual lesson with its own topology
- **Task**: Questions or actions students must complete

### Creating a Training

1. Go to **Training** tab
2. Click **"Create New Training"**
3. Fill in training details:
   - Title
   - Description
   - Difficulty level
4. Add levels
5. Add tasks to each level
6. Save the training

### Task Types

**Quiz Tasks:**
- Multiple choice or text answer
- Automatically graded
- Case-insensitive matching

**Action Tasks:**
- Hands-on challenges
- Require verification scripts
- Custom validation logic

### Running a Training

1. Select a training from the list
2. Click **"Start Training Run"**
3. Specify participants
4. Deploy level topologies as needed
5. Students submit answers
6. Track progress and scores

### Training Features

- **Hints**: Built-in hint system with score penalties
- **Progress Tracking**: Real-time student progress
- **Auto-grading**: Automatic evaluation of quiz answers
- **Console Streaming**: Live VM console output
- **Level Deployment**: Deploy/destroy VMs per level

## Settings

Configure CyberRanger to your preferences.

### Available Settings

- **Theme**: Light/Dark mode toggle
- **API Endpoint**: Backend API URL
- **Console Settings**: NoVNC configuration
- **Network Settings**: Default network configuration

### Range Mapper

Enable network discovery and mapping:
1. Set `RANGE_MAPPER_ENABLE=1` in docker-compose.yml
2. Restart containers
3. Use the Range Mapper API to scan networks

## Keyboard Shortcuts

- **Dashboard**: `Ctrl+1`
- **Images**: `Ctrl+2`
- **Topology Builder**: `Ctrl+3`
- **Training**: `Ctrl+4`
- **Settings**: `Ctrl+5`

## Best Practices

### VM Management
- Use descriptive names for VMs
- Clean up unused VMs regularly
- Monitor resource usage
- Stop VMs when not in use

### Image Organization
- Keep images in the `images/` directory
- Use consistent naming conventions
- Document custom images
- Compress large images with qcow2

### Network Security
- Use isolated networks for security testing
- Don't expose VMs directly to the internet
- Regularly update firewall rules
- Monitor NoVNC port access

### Training Design
- Start with simple scenarios
- Provide clear instructions
- Test trainings before deployment
- Include hints for difficult tasks
- Use realistic scenarios

## Tips & Tricks

1. **Quick VM Creation**: Use Cloud-init for pre-configured VMs
2. **Scenario Templates**: Save common topologies as scenarios
3. **Batch Operations**: Deploy multiple VMs simultaneously
4. **Console Recording**: Record console sessions for review
5. **Network Isolation**: Use separate networks for different teams

## Next Steps

- Learn about [Architecture](Architecture.md) to understand how CyberRanger works
- Check the [API Reference](API-Reference.md) for automation
- Read [Troubleshooting](Troubleshooting.md) for common issues
