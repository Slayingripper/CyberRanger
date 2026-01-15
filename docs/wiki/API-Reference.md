# API Reference

Complete API documentation for CyberRanger backend endpoints.

## Base URL

```
http://localhost:8001/api
```

## Authentication

Currently, the API does not require authentication. This should be added for production deployments.

---

## Virtual Machines

### List VMs

Get all virtual machines.

```http
GET /api/vms
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "test-vm",
    "uuid": "abc123...",
    "state": 1,
    "memory": 2048,
    "vcpus": 2,
    "vnc_port": "5900",
    "websocket_port": 6080
  }
]
```

**VM States:**
- `0`: Shut off
- `1`: Running
- `3`: Paused

### Get Runtime VM Info

Get VMs with network interface details.

```http
GET /api/runtime/vms
```

**Response:**
```json
[
  {
    "name": "test-vm",
    "interfaces": [
      {
        "name": "eth0",
        "mac": "52:54:00:xx:xx:xx",
        "network": "default",
        "ips": ["192.168.122.10"]
      }
    ]
  }
]
```

### Create VM

Create a new virtual machine.

```http
POST /api/vms
```

**Request Body:**
```json
{
  "name": "my-vm",
  "memory_mb": 2048,
  "vcpus": 2,
  "image_path": "/app/images/ubuntu.qcow2",
  "iso_path": null,
  "cloud_init": {
    "username": "user",
    "password": "password",
    "packages": "vim\nnmap"
  },
  "network_name": "default",
  "network_names": ["default", "isolated-net"]
}
```

**Parameters:**
- `name` (required): VM name
- `memory_mb` (required): RAM in MB
- `vcpus` (required): Number of CPUs
- `image_path` (optional): Path to disk image
- `iso_path` (optional): Path to ISO image
- `cloud_init` (optional): Cloud-init configuration
- `network_name` (optional): Single network (default: "default")
- `network_names` (optional): Multiple networks

**Response:**
```json
{
  "status": "success",
  "message": "VM created successfully",
  "name": "my-vm",
  "vnc_port": 5901
}
```

### Start VM

Start a virtual machine.

```http
POST /api/vms/{name}/start
```

**Response:**
```json
{
  "status": "started"
}
```

### Stop VM

Stop a virtual machine.

```http
POST /api/vms/{name}/stop
```

**Response:**
```json
{
  "status": "stopped"
}
```

### Delete VM

Delete a virtual machine and its disk.

```http
DELETE /api/vms/{name}
```

**Response:**
```json
{
  "status": "deleted"
}
```

---

## Images

### List Images

Get all available images.

```http
GET /api/images
```

**Response:**
```json
[
  {
    "name": "Ubuntu 20.04",
    "path": "ubuntu-20.04.img",
    "host_path": "/app/images/ubuntu-20.04.img",
    "size": 2361393152,
    "format": "img"
  }
]
```

### Download Image

Download an image from a URL.

```http
POST /api/images/download
```

**Request Body:**
```json
{
  "url": "https://example.com/image.iso",
  "filename": "custom-image.iso",
  "extract": {
    "format": "gz",
    "output_filename": "image.img"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "container_path": "/app/images/image.img",
  "host_path": "/path/to/images/image.img"
}
```

---

## Topology

### Cache Topology

Save topology design for later deployment.

```http
POST /api/topology/cache
```

**Request Body:**
```json
{
  "nodes": [...],
  "edges": [...]
}
```

### Get Cached Topology

Retrieve cached topology.

```http
GET /api/topology/cache
```

**Response:**
```json
{
  "topology": {
    "nodes": [...],
    "edges": [...]
  },
  "updated_at": 1234567890.0
}
```

### Deploy Topology (Synchronous)

Deploy a network topology immediately.

```http
POST /api/topology/deploy
```

**Request Body:**
```json
{
  "scenario": {
    "name": "Pentest Lab",
    "team": "Red",
    "objective": "Gain root access",
    "difficulty": "medium",
    "network_prefix": "pentest",
    "sources": {
      "kali-linux": "https://example.com/kali.iso"
    }
  },
  "nodes": [
    {
      "id": "node-1",
      "label": "Attacker",
      "config": {
        "image": "kali-linux",
        "cpu": 2,
        "ram": 2048,
        "assets": [
          {
            "type": "package",
            "value": "nmap"
          },
          {
            "type": "command",
            "value": "echo 'Setup complete'"
          }
        ]
      }
    }
  ],
  "edges": [
    {
      "source": "node-1",
      "target": "node-2"
    }
  ]
}
```

**Asset Types:**
- `package`: Install a package
- `command`: Run a shell command
- `ansible`: Execute Ansible playbook

**Response:**
```json
{
  "status": "deployment_processed",
  "results": [
    {
      "status": "success",
      "name": "Attacker_node-1",
      "vnc_port": 5900
    }
  ]
}
```

### Deploy Topology (Job-based)

Start asynchronous topology deployment with progress tracking.

```http
POST /api/topology/deploy-jobs
```

**Request Body:** Same as synchronous deploy

**Response:**
```json
{
  "job_id": "abc123-def456"
}
```

### Get Deployment Job Status

Monitor deployment progress.

```http
GET /api/topology/deploy-jobs/{job_id}
```

**Response:**
```json
{
  "job_id": "abc123-def456",
  "status": "running",
  "message": "Creating virtual machines",
  "created_at": 1234567890.0,
  "started_at": 1234567891.0,
  "finished_at": null,
  "progress": {
    "phase": "vms",
    "downloads": {
      "kali.iso": {
        "status": "downloaded",
        "current": 1073741824,
        "total": 1073741824,
        "percent": 100,
        "speed_bps": 10485760
      }
    },
    "nodes": {
      "node-1": {
        "label": "Attacker",
        "status": "running"
      }
    }
  },
  "result": null
}
```

**Job Statuses:**
- `queued`: Waiting to start
- `running`: In progress
- `completed`: Successfully finished
- `failed`: Error occurred

**Progress Phases:**
- `queued`: Job created
- `downloads`: Downloading images
- `vms`: Creating virtual machines
- `done`: All complete

---

## Trainings

### List Trainings

Get all training courses.

```http
GET /api/trainings
```

**Response:**
```json
[
  {
    "id": "training-123",
    "title": "Web Security Basics",
    "description": "Learn web security fundamentals",
    "difficulty": "easy",
    "levels": [...]
  }
]
```

### Get Training

Get a specific training by ID.

```http
GET /api/trainings/{training_id}
```

### Create Training

Create a new training course.

```http
POST /api/trainings
```

**Request Body:**
```json
{
  "title": "Web Security Basics",
  "description": "Learn web security fundamentals",
  "difficulty": "easy",
  "levels": [
    {
      "title": "SQL Injection",
      "description": "Learn to identify and exploit SQL injection",
      "topology": {
        "vms": [
          {
            "name": "web-server",
            "image": "ubuntu-20.04.img",
            "memory": 1024,
            "vcpus": 1
          }
        ]
      },
      "tasks": [
        {
          "question": "What is the admin password?",
          "type": "quiz",
          "answer": "admin123",
          "hints": [
            "Try common passwords",
            "Check the database directly"
          ]
        }
      ]
    }
  ]
}
```

**Response:**
```json
{
  "id": "training-123",
  "title": "Web Security Basics",
  ...
}
```

### Update Training

Update an existing training.

```http
PUT /api/trainings/{training_id}
```

**Request Body:** Same as create

### Delete Training

Delete a training course.

```http
DELETE /api/trainings/{training_id}
```

### Deploy Training Level

Deploy VMs for a specific training level.

```http
POST /api/trainings/{training_id}/levels/{level_idx}/deploy
```

**Response:**
```json
{
  "status": "deployed",
  "vms": [
    {
      "name": "t12345678_l0_webserver",
      "status": "created"
    }
  ]
}
```

### Destroy Training Level

Remove all VMs for a training level.

```http
POST /api/trainings/{training_id}/levels/{level_idx}/destroy
```

### Get Level Status

Check status of training level VMs.

```http
GET /api/trainings/{training_id}/levels/{level_idx}/status
```

**Response:**
```json
{
  "vms": [
    {
      "name": "t12345678_l0_webserver",
      "state": 1,
      "state_desc": "running"
    }
  ]
}
```

### Upload Training

Upload a training definition file (JSON or YAML).

```http
POST /api/trainings/upload
```

**Form Data:**
- `file`: Training definition file

---

## Training Runs

### Create Training Run

Start a new training run for participants.

```http
POST /api/training-runs?definition_id={training_id}&participants[]={name1}&participants[]={name2}
```

**Response:**
```json
{
  "run_id": "run-abc123",
  "definition_id": "training-123",
  "participants": ["alice", "bob"],
  "state": "in_progress",
  "current_level": 0,
  "score": 0
}
```

### Get Training Run

Get run details and progress.

```http
GET /api/training-runs/{run_id}
```

### Submit Answer

Submit an answer for a task.

```http
POST /api/training-runs/{run_id}/levels/{level_idx}/submit
```

**Request Body:**
```json
{
  "task_id": "task-123",
  "answer": "admin123"
}
```

**Response:**
```json
{
  "correct": true,
  "message": "Correct! Moving to next level.",
  "score": 100
}
```

### Request Hint

Get a hint for a task (with score penalty).

```http
POST /api/training-runs/{run_id}/levels/{level_idx}/hint
```

**Request Body:**
```json
{
  "task_id": "task-123"
}
```

**Response:**
```json
{
  "hint": "Try common passwords",
  "penalty": 10,
  "remaining_hints": 1
}
```

---

## Range Mapper

### Scan Network

Discover hosts on a network.

```http
POST /api/range-mapper/scan
```

**Request Body:**
```json
{
  "network": "192.168.122.0/24",
  "ports": "22,80,443"
}
```

**Response:**
```json
{
  "hosts": [
    {
      "ip": "192.168.122.10",
      "hostname": "web-server",
      "ports": [
        {"port": 80, "state": "open", "service": "http"},
        {"port": 443, "state": "open", "service": "https"}
      ]
    }
  ]
}
```

---

## Proxy (NoVNC)

### WebSocket Connection

Connect to VM console via WebSocket.

```
ws://localhost:8001/api/proxy/{vm_name}
```

This endpoint forwards WebSocket connections to the VM's VNC server.

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "detail": "Error message here"
}
```

**Common HTTP Status Codes:**
- `200`: Success
- `400`: Bad Request (invalid input)
- `404`: Not Found (resource doesn't exist)
- `500`: Internal Server Error

---

## Rate Limiting

Currently no rate limiting is implemented. Consider adding in production.

---

## Versioning

API version is not currently in the URL. Future versions may use:
```
/api/v1/vms
/api/v2/vms
```

---

## Examples

### Python Example

```python
import requests

API_URL = "http://localhost:8001/api"

# Create a VM
response = requests.post(f"{API_URL}/vms", json={
    "name": "test-vm",
    "memory_mb": 2048,
    "vcpus": 2,
    "iso_path": "/app/images/ubuntu.iso"
})
print(response.json())

# List VMs
vms = requests.get(f"{API_URL}/vms").json()
for vm in vms:
    print(f"{vm['name']}: {vm['state']}")

# Start VM
requests.post(f"{API_URL}/vms/test-vm/start")
```

### JavaScript Example

```javascript
const API_URL = 'http://localhost:8001/api';

// Create a VM
async function createVM() {
  const response = await fetch(`${API_URL}/vms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: 'test-vm',
      memory_mb: 2048,
      vcpus: 2,
      iso_path: '/app/images/ubuntu.iso'
    })
  });
  const data = await response.json();
  console.log(data);
}

// List VMs
async function listVMs() {
  const response = await fetch(`${API_URL}/vms`);
  const vms = await response.json();
  vms.forEach(vm => {
    console.log(`${vm.name}: ${vm.state}`);
  });
}
```

### cURL Example

```bash
# Create a VM
curl -X POST http://localhost:8001/api/vms \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-vm",
    "memory_mb": 2048,
    "vcpus": 2,
    "iso_path": "/app/images/ubuntu.iso"
  }'

# List VMs
curl http://localhost:8001/api/vms

# Start VM
curl -X POST http://localhost:8001/api/vms/test-vm/start

# Delete VM
curl -X DELETE http://localhost:8001/api/vms/test-vm
```
