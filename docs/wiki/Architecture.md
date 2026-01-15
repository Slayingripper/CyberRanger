# Architecture

This document describes the technical architecture of CyberRanger.

## System Overview

CyberRanger follows a client-server architecture with a React frontend, FastAPI backend, and Libvirt for virtualization.

```
┌─────────────────┐
│  Web Browser    │
│   (React UI)    │
└────────┬────────┘
         │ HTTP/WS
         ▼
┌─────────────────┐
│  Frontend       │
│  (Vite Server)  │
└────────┬────────┘
         │ REST API
         ▼
┌─────────────────┐      ┌──────────────┐
│  Backend        │◄────►│  Libvirt     │
│  (FastAPI)      │      │  (KVM/QEMU)  │
└────────┬────────┘      └──────┬───────┘
         │                      │
         ▼                      ▼
┌─────────────────┐      ┌──────────────┐
│  File System    │      │  Virtual     │
│  (Images/Data)  │      │  Machines    │
└─────────────────┘      └──────────────┘
```

## Components

### Frontend (React + Vite)

**Technology Stack:**
- React 18.2
- Vite for build tooling
- Tailwind CSS for styling
- Lucide React for icons
- React Router for navigation
- Axios for HTTP requests
- NoVNC for console access
- React Flow for topology visualization

**Key Features:**
- Single Page Application (SPA)
- Real-time VM status updates
- Visual topology builder
- In-browser VM console
- Responsive design

**File Structure:**
```
frontend/
├── src/
│   ├── components/      # React components
│   │   ├── Images.jsx
│   │   ├── NetworkBuilder.jsx
│   │   ├── Training.jsx
│   │   ├── VNCConsole.jsx
│   │   └── ...
│   ├── context/         # React context providers
│   ├── lib/            # Utility functions
│   ├── App.jsx         # Main application
│   └── main.jsx        # Entry point
├── index.html
├── package.json
└── vite.config.js
```

### Backend (FastAPI + Python)

**Technology Stack:**
- FastAPI 0.109
- Uvicorn ASGI server
- Libvirt Python bindings
- WebSockets for real-time updates
- Pydantic for data validation
- PyYAML for scenario parsing

**Core Modules:**

#### 1. API Layer (`app/api/`)

**routes.py** - VM and Topology Management
- VM CRUD operations
- Topology deployment
- Network management
- Job-based deployment

**images.py** - Image Management
- List available images
- Download images from URLs
- Extract compressed images
- Manage image metadata

**trainings.py** - Training System
- Training CRUD operations
- Level deployment/destruction
- Upload training definitions
- Training status monitoring

**training_runs.py** - Training Execution
- Create training runs
- Submit answers
- Request hints
- Track progress

**proxy.py** - WebSocket Proxy
- NoVNC WebSocket forwarding
- Console access management

**range_mapper.py** - Network Discovery
- Scan VM networks
- Discover hosts
- Port scanning

#### 2. Core Layer (`app/core/`)

**vm_manager.py** - Virtual Machine Management
- Libvirt connection management
- VM lifecycle (create/start/stop/delete)
- Cloud-init integration
- VNC configuration
- Network attachment

**image_manager.py** - Image Operations
- Download images with progress tracking
- Extract archives (gz, bz2, 7z)
- Verify image integrity
- Cache management

**deploy_jobs.py** - Asynchronous Deployment
- Job queue management
- Progress tracking
- Status updates
- Result storage

**event_bus.py** - Event System
- WebSocket event distribution
- Training run events
- Console streaming
- Real-time updates

**proxy_manager.py** - Console Proxy
- Websockify management
- Port allocation
- Proxy lifecycle

**range_mapper.py** - Network Scanning
- Nmap integration
- Host discovery
- Service detection

### Virtualization Layer (Libvirt + KVM)

**Libvirt** provides:
- VM lifecycle management
- Network management
- Storage management
- Remote access (VNC)

**KVM/QEMU** provides:
- Hardware virtualization
- Device emulation
- Performance optimization

### Data Storage

**File-based Storage:**
```
CyberRanger/
├── images/              # VM disk images
├── disks/              # Runtime VM disks
├── scenarios/          # YAML scenario definitions
└── backend/
    ├── data/
    │   └── trainings/  # Training definitions (JSON)
    └── training_runs/  # Active training runs (JSON)
```

**In-Memory Storage:**
- Topology cache
- Job status
- Event subscriptions

## Key Workflows

### VM Creation Flow

```
1. User submits VM creation request (Frontend)
   ↓
2. Frontend sends POST /api/vms (API Request)
   ↓
3. Backend validates request (Pydantic)
   ↓
4. vm_manager.create_vm() called
   ↓
5. Generate Cloud-init ISO (if configured)
   ↓
6. Create libvirt domain XML
   ↓
7. Define domain in libvirt
   ↓
8. Allocate VNC port
   ↓
9. Start VM
   ↓
10. Return VM details to frontend
```

### Topology Deployment Flow

```
1. User designs topology (Frontend)
   ↓
2. Frontend sends POST /api/topology/deploy-jobs
   ↓
3. Backend creates deployment job
   ↓
4. Job worker starts asynchronously
   ↓
5. Calculate network components
   ↓
6. Create/ensure libvirt networks
   ↓
7. Download required images (with progress)
   ↓
8. For each node:
   │  ├── Build cloud-init configuration
   │  ├── Create VM
   │  └── Update progress
   ↓
9. Mark job as completed
   ↓
10. Frontend polls for job status
```

### Training Run Flow

```
1. Create training run (POST /api/training-runs)
   ↓
2. Deploy level topology
   ↓
3. Student interacts with VMs
   ↓
4. Student submits answer
   ↓
5. Backend evaluates answer
   ↓
6. Update run state
   ↓
7. Advance to next level (if correct)
   ↓
8. Repeat until all levels complete
```

## Network Architecture

### Network Types

**1. NAT Networks** (Default)
- DHCP enabled
- Internet access via NAT
- Isolated per component
- Subnet: `192.168.X.0/24`

**2. Isolated Networks**
- No DHCP
- No internet access
- Used for OPNsense LANs
- Manual IP configuration required

**3. Bridge Networks**
- Direct host access
- External connectivity
- Shared with host

### Network Naming

Networks are named based on deployment:
```
cyberange-{slug}-{component_id}        # NAT network
cyberange-{slug}-lan-{component_id}    # Isolated LAN
```

Bridge names are hashed to avoid conflicts:
```
cr{hash}{component_id}  # Max 15 characters
```

### Connected Components

The topology builder analyzes node connections:
1. Build adjacency graph from edges
2. Find connected components
3. Create one network per component
4. Attach VMs to their component's network

### OPNsense Integration

When a component contains an OPNsense node:
1. Create isolated LAN network (no DHCP)
2. Create NAT WAN network (default)
3. Attach OPNsense to both networks
4. Other nodes attach to LAN only
5. Configure OPNsense as router/firewall

## Cloud-Init Integration

CyberRanger uses Cloud-init for automated VM configuration.

### Cloud-Init Process

```
1. Generate user-data YAML
   ├── Set username/password
   ├── Add SSH keys
   ├── List packages to install
   └── Add run commands
   ↓
2. Generate meta-data YAML
   ├── Instance ID
   ├── Hostname
   └── Network config
   ↓
3. Create ISO filesystem
   ├── user-data
   ├── meta-data
   └── network-config
   ↓
4. Attach ISO to VM as CD-ROM
   ↓
5. VM boots and executes cloud-init
```

### Supported Features

- User creation
- Password configuration
- Package installation
- Shell command execution
- Ansible playbook execution
- Network configuration

## API Architecture

### RESTful Design

All endpoints follow REST principles:
- `GET` for reading data
- `POST` for creating resources
- `PUT` for updating resources
- `DELETE` for removing resources

### Request/Response Format

**Requests:**
- JSON request bodies
- Pydantic validation
- Type checking

**Responses:**
- JSON responses
- Consistent error format
- HTTP status codes

### WebSocket Support

**Event Bus:**
- Real-time updates
- Training run events
- Console streaming
- Progress tracking

**Console Proxy:**
- NoVNC WebSocket tunneling
- VNC protocol forwarding
- Connection management

## Security Considerations

### Network Isolation

- VMs in separate networks by default
- No direct internet access unless configured
- NAT for outbound connections
- Firewall between networks

### Access Control

- Libvirt socket access via Docker
- Host file system isolation
- No direct SSH to VMs (use console)
- User authentication (not implemented yet)

### Best Practices

1. **Run with minimal privileges**
2. **Isolate networks properly**
3. **Use read-only base images**
4. **Monitor VM resource usage**
5. **Regular security updates**
6. **Firewall NoVNC ports**

## Performance Optimization

### VM Performance

- KVM hardware acceleration
- VirtIO drivers for better I/O
- Balloon memory management
- CPU pinning (optional)

### Image Management

- QCOW2 compression
- Copy-on-write disk images
- Shared base images
- Lazy allocation

### Frontend Performance

- Vite HMR for development
- Code splitting
- Lazy loading components
- Optimized bundle size

### Backend Performance

- Async/await for I/O operations
- Connection pooling
- Job-based deployment
- Progress streaming

## Scalability

### Horizontal Scaling

Multiple backend instances can:
- Share libvirt host
- Load balance API requests
- Distribute deployments

### Vertical Scaling

- Add more CPU cores
- Increase host RAM
- Use faster storage (SSD/NVMe)
- Optimize VM allocations

### Resource Limits

Default limits per VM:
- Max 8 vCPUs
- Max 8192 MB RAM
- Max 100 GB disk

## Monitoring & Logging

### Logs

**Backend Logs:**
```bash
docker logs cyberrange-backend
```

**Frontend Logs:**
```bash
docker logs cyberrange-frontend
```

**Libvirt Logs:**
```bash
journalctl -u libvirtd
```

### Metrics

Track these metrics for health:
- VM count
- CPU usage per VM
- Memory usage per VM
- Network bandwidth
- Disk I/O
- API response times

## Technology Choices

### Why FastAPI?

- Modern async Python framework
- Automatic API documentation
- Type validation with Pydantic
- WebSocket support
- High performance

### Why React + Vite?

- Fast development with HMR
- Modern React features
- Optimized builds
- Large ecosystem

### Why Libvirt?

- Industry standard
- Mature and stable
- Cross-platform support
- Rich feature set
- Active development

### Why KVM/QEMU?

- Native Linux virtualization
- Near-native performance
- Wide hardware support
- Free and open source
