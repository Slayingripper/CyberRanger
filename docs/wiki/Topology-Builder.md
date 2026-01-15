# Topology Builder

The Topology Builder is a visual tool for designing and deploying custom network scenarios in CyberRanger.

## Overview

The Topology Builder allows you to:
- Design network topologies with a drag-and-drop interface
- Configure virtual machines and their properties
- Define network connections between VMs
- Automate VM configuration with packages and scripts
- Deploy complete scenarios with one click
- Track deployment progress in real-time

## Interface Components

### Canvas

The main workspace where you design your topology:
- Drag nodes from the palette
- Connect nodes with edges
- Pan and zoom the view
- Select and edit nodes

### Node Palette

Available node types:
- **Computer**: Standard workstation or server
- **Router**: Network routing device
- **Firewall**: Security appliance
- **Switch**: Network switch
- **Custom**: Any other device type

### Properties Panel

Configure selected nodes:
- Display label
- Image selection
- CPU allocation
- RAM allocation
- Asset configuration

### Scenario Panel

Define scenario metadata:
- Scenario name
- Team assignment
- Training objective
- Difficulty level
- Image sources

## Creating a Topology

### Step 1: Add Nodes

1. Click or drag a node type from the palette
2. Place it on the canvas
3. Repeat for all required nodes

**Keyboard Shortcuts:**
- `C`: Add computer node
- `R`: Add router node
- `F`: Add firewall node
- `Del`: Delete selected node

### Step 2: Configure Nodes

Click on a node to configure:

**Basic Settings:**
```
Label: "Web Server"
Image: ubuntu-20.04
CPU: 2
RAM: 2048 MB
```

**Advanced Settings:**
- Network interfaces
- Cloud-init configuration
- Automation scripts

### Step 3: Connect Nodes

Create network connections:
1. Click the source node
2. Drag to the target node
3. Release to create an edge

**Connection Rules:**
- Each edge represents a shared network
- Connected nodes can communicate
- Disconnected groups are isolated

### Step 4: Configure Assets

Assets are automatically installed/executed on boot:

**Package Assets:**
```json
{
  "type": "package",
  "value": "nginx"
}
```

**Command Assets:**
```json
{
  "type": "command",
  "value": "systemctl enable nginx"
}
```

**Ansible Assets:**
```json
{
  "type": "ansible",
  "playbook": "---\n- hosts: localhost\n  tasks:\n    - name: Install web server\n      apt:\n        name: nginx\n        state: present",
  "playbook_name": "webserver.yml"
}
```

### Step 5: Deploy

Two deployment options:

**Quick Deploy:**
- Click "Deploy Topology"
- Synchronous deployment
- All VMs created immediately
- Results returned when complete

**Job Deploy:**
- Click "Deploy as Job"
- Asynchronous deployment
- Track progress in real-time
- Download images automatically
- Monitor each node's status

## Node Configuration

### Image Selection

Specify the OS image to use:

**Predefined Keys:**
- `kali-linux`: Kali Linux
- `ubuntu-20.04`: Ubuntu 20.04
- `windows-10`: Windows 10
- `openwrt`: OpenWrt router
- `opnsense`: OPNsense firewall

**Direct Paths:**
- `ubuntu-20.04.img`
- `kali-linux-2023.qcow2`
- `debian-12.iso`

**Auto-Download:**
Define in scenario sources:
```json
{
  "sources": {
    "kali-linux": "https://example.com/kali.iso"
  }
}
```

### Resource Allocation

**CPU:**
- Minimum: 1 vCPU
- Maximum: 8 vCPUs
- Recommended: 2 vCPUs for most workloads

**RAM:**
- Minimum: 512 MB
- Maximum: 8192 MB (8 GB)
- Recommended: 2048 MB (2 GB) for workstations

**Disk:**
- Automatically allocated
- Based on image size
- Copy-on-write (qcow2)

### Asset Configuration

**Supported Asset Types:**

1. **Packages** - Install software
   ```json
   {
     "type": "package",
     "value": "nmap"
   }
   ```

2. **Commands** - Run shell commands
   ```json
   {
     "type": "command",
     "value": "echo 'Setup complete' > /tmp/done"
   }
   ```

3. **Ansible Playbooks** - Complex automation
   ```json
   {
     "type": "ansible",
     "playbook": "...",
     "install": true,
     "extra_vars": {
       "web_port": 8080
     }
   }
   ```

## Network Design

### Network Components

The Topology Builder automatically creates networks based on node connections:

**Connected Components:**
- Nodes connected by edges
- Share the same network
- Can communicate freely

**Example:**
```
Node A --- Node B --- Node C
```
All three nodes share one network.

**Disconnected Components:**
```
Node A --- Node B    Node C --- Node D
```
Two separate networks are created.

### Network Types

**NAT Networks:**
- Default for most scenarios
- DHCP enabled
- Internet access via NAT
- Subnet: `192.168.X.0/24`

**Isolated Networks:**
- No DHCP
- No internet access
- Used for OPNsense LANs
- Manual IP configuration

### OPNsense Integration

When an OPNsense node is detected:

1. **Create Networks:**
   - WAN: NAT network (default)
   - LAN: Isolated network (no DHCP)

2. **Attach OPNsense:**
   - WAN interface → NAT network
   - LAN interface → Isolated network

3. **Attach Other Nodes:**
   - Connect to LAN network only

4. **Configure OPNsense:**
   - Act as router/firewall
   - Provide DHCP on LAN
   - NAT/routing between networks

**Example OPNsense Topology:**
```
Internet
   |
   ↓
WAN (OPNsense) LAN
                |
        ┌───────┼───────┐
        ↓       ↓       ↓
    Client1 Client2 Server
```

## Scenario Configuration

### Metadata

Define scenario properties:

```json
{
  "name": "Web Application Pentest",
  "team": "Red Team",
  "objective": "Identify and exploit web vulnerabilities",
  "difficulty": "medium"
}
```

**Team Options:**
- `Red Team`: Offensive security
- `Blue Team`: Defensive security
- `Purple Team`: Combined red/blue
- `General`: Any team

**Difficulty Levels:**
- `easy`: Beginner-friendly
- `medium`: Intermediate
- `hard`: Advanced

### Network Prefix

Control network naming:

```json
{
  "network_prefix": "pentest"
}
```

**With prefix:**
- `cyberange-pentest-c0`
- `cyberange-pentest-c1`

**Without prefix (random):**
- `cyberange-topology-a1b2c3d4-c0`
- `cyberange-topology-a1b2c3d4-c1`

### Image Sources

Auto-download images:

```json
{
  "sources": {
    "kali-linux": "https://cdimage.kali.org/kali-2023.4/kali-linux-2023.4-installer-amd64.iso",
    "ubuntu-20.04": {
      "url": "https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img",
      "filename": "ubuntu-20.04.img"
    },
    "compressed-image": {
      "url": "https://example.com/image.img.gz",
      "filename": "image.img.gz",
      "extract": {
        "format": "gz",
        "output_filename": "image.img"
      }
    }
  }
}
```

**Source Formats:**

**Simple URL:**
```json
"image-name": "https://example.com/image.iso"
```

**Detailed Config:**
```json
"image-name": {
  "url": "https://example.com/image.iso",
  "filename": "custom-name.iso"
}
```

**Compressed Image:**
```json
"image-name": {
  "url": "https://example.com/image.img.gz",
  "filename": "image.img.gz",
  "extract": {
    "format": "gz",
    "output_filename": "image.img"
  }
}
```

**Supported Compression:**
- `.gz` (gzip)
- `.bz2` (bzip2)
- `.7z` (7-zip)

## Deployment

### Synchronous Deployment

**Process:**
1. Click "Deploy Topology"
2. Backend processes request
3. Creates networks
4. Creates all VMs
5. Returns results

**Use When:**
- Small topologies (1-3 VMs)
- Fast image downloads
- Immediate results needed

**Limitations:**
- No progress tracking
- Request timeout on large deployments
- No image download progress

### Asynchronous Deployment (Recommended)

**Process:**
1. Click "Deploy as Job"
2. Job created with ID
3. Backend processes in background
4. Frontend polls for status
5. Real-time progress updates

**Phases:**

**1. Queued**
```json
{
  "phase": "queued",
  "status": "Job created, waiting to start"
}
```

**2. Downloads**
```json
{
  "phase": "downloads",
  "downloads": {
    "kali.iso": {
      "status": "downloading",
      "current": 524288000,
      "total": 1073741824,
      "percent": 48,
      "speed_bps": 10485760,
      "eta_seconds": 52.4
    }
  }
}
```

**3. VMs**
```json
{
  "phase": "vms",
  "nodes": {
    "node-1": {
      "label": "Attacker",
      "status": "running"
    },
    "node-2": {
      "label": "Target",
      "status": "creating"
    }
  }
}
```

**4. Done**
```json
{
  "phase": "done",
  "status": "completed"
}
```

### Monitoring Deployment

**API Polling:**
```javascript
const jobId = response.job_id;
const interval = setInterval(async () => {
  const status = await fetch(`/api/topology/deploy-jobs/${jobId}`);
  const data = await status.json();
  
  if (data.status === 'completed' || data.status === 'failed') {
    clearInterval(interval);
  }
  
  console.log('Progress:', data.progress);
}, 2000);
```

**Progress Display:**
- Download progress bars
- Node status indicators
- Overall completion percentage
- Error messages

## Example Topologies

### 1. Basic Pentest Lab

**Nodes:**
- Attacker (Kali Linux)
- Target (Metasploitable)

**Network:**
- Direct connection
- Single NAT network

**Configuration:**
```json
{
  "scenario": {
    "name": "Basic Pentest",
    "team": "Red Team",
    "difficulty": "easy"
  },
  "nodes": [
    {
      "id": "attacker",
      "label": "Kali Attacker",
      "config": {
        "image": "kali-linux",
        "cpu": 2,
        "ram": 2048,
        "assets": [
          {"type": "package", "value": "nmap"},
          {"type": "package", "value": "metasploit-framework"}
        ]
      }
    },
    {
      "id": "target",
      "label": "Metasploitable",
      "config": {
        "image": "metasploitable",
        "cpu": 1,
        "ram": 1024,
        "assets": []
      }
    }
  ],
  "edges": [
    {"source": "attacker", "target": "target"}
  ]
}
```

### 2. Segmented Network

**Nodes:**
- Firewall (OPNsense)
- Web Server (Ubuntu)
- Database Server (Ubuntu)
- Attacker (Kali)

**Network:**
- OPNsense WAN (internet)
- OPNsense LAN (internal)
- Servers on LAN
- Attacker on WAN

**Topology:**
```
WAN --- (OPNsense) --- LAN
  |                     |
Attacker          Web ---- DB
```

### 3. Multi-Tier Application

**Nodes:**
- Load Balancer
- Web Server 1
- Web Server 2
- Application Server
- Database Server

**Network:**
- Frontend network (LB + Web)
- Backend network (App + DB)

**Topology:**
```
    Load Balancer
      /       \
   Web1      Web2
      \       /
   Application
        |
    Database
```

## Automation Features

### ISO Installation Automation

For ISO-based VMs, automate installation:

```json
{
  "automation": {
    "type": "send_text",
    "text": "yes\n",
    "delay_seconds": 45,
    "retries": 3,
    "retry_delay_seconds": 15
  }
}
```

**Use Cases:**
- Accept license agreements
- Confirm installation
- Set up initial configuration

### Cloud-Init Integration

For cloud images, use cloud-init:

```json
{
  "cloud_init": {
    "username": "admin",
    "password": "secure123",
    "packages": "nginx\nmysql-server",
    "runcmd": [
      "systemctl enable nginx",
      "systemctl start nginx"
    ]
  }
}
```

## Best Practices

### Design

1. **Start Simple**
   - Begin with 2-3 nodes
   - Add complexity gradually
   - Test frequently

2. **Logical Grouping**
   - Group related services
   - Separate networks logically
   - Use meaningful labels

3. **Resource Planning**
   - Calculate total resource needs
   - Leave headroom for host
   - Monitor during deployment

### Images

1. **Use Cloud Images**
   - Faster deployment
   - Cloud-init support
   - Smaller size

2. **Pre-configure Images**
   - Install common tools
   - Set default configs
   - Document customizations

3. **Leverage Auto-download**
   - Define sources in scenario
   - Version control URLs
   - Use checksums

### Networks

1. **Minimize Connections**
   - Only connect what's needed
   - Reduces attack surface
   - Clearer design

2. **Use Firewalls**
   - Add OPNsense for segmentation
   - Control traffic flow
   - Log connections

3. **Document Network**
   - Label networks clearly
   - Document IP schemes
   - Note security zones

## Troubleshooting

### Nodes Not Connecting

1. Verify edge exists
2. Check network creation
3. Review libvirt networks
4. Test with ping

### Deployment Fails

1. Check image paths
2. Verify sufficient resources
3. Review backend logs
4. Test image manually

### Images Not Downloading

1. Verify URL is accessible
2. Check network connectivity
3. Review proxy settings
4. Test download manually

### OPNsense Not Routing

1. Verify two interfaces attached
2. Check WAN/LAN assignment
3. Configure firewall rules
4. Enable routing

## Advanced Topics

### Custom Node Types

Add custom node types by extending the palette:

```javascript
const customNode = {
  type: 'database',
  label: 'Database',
  icon: 'database',
  defaultConfig: {
    cpu: 2,
    ram: 4096
  }
};
```

### Topology Templates

Save common topologies:

```javascript
const template = {
  name: "LAMP Stack",
  nodes: [...],
  edges: [...]
};
```

### Export/Import

**Export Topology:**
```javascript
const topology = {
  scenario: {...},
  nodes: [...],
  edges: [...]
};
const json = JSON.stringify(topology, null, 2);
downloadFile('topology.json', json);
```

**Import Topology:**
```javascript
const topology = JSON.parse(fileContent);
loadTopology(topology);
```

## See Also

- [User Guide](User-Guide.md) - Platform basics
- [Training System](Training-System.md) - Creating training scenarios
- [API Reference](API-Reference.md) - API integration
- [Architecture](Architecture.md) - Technical details
