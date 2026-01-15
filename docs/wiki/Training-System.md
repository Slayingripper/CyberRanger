# Training System

Comprehensive guide to the CyberRanger Training System for creating and running cybersecurity training courses.

## Overview

The Training System allows instructors to create structured, multi-level cybersecurity training courses with:
- Hands-on virtual machine environments
- Automated grading
- Progress tracking
- Hints and guidance
- Real-time console access

## Architecture

```
Training
  ├── Level 1
  │   ├── Topology (VMs + Network)
  │   └── Tasks
  │       ├── Task 1 (Quiz)
  │       └── Task 2 (Action)
  ├── Level 2
  │   ├── Topology
  │   └── Tasks
  └── Level 3
      ├── Topology
      └── Tasks
```

## Creating a Training

### Step 1: Define Training Metadata

```json
{
  "title": "Web Application Security",
  "description": "Learn to identify and exploit common web vulnerabilities",
  "difficulty": "medium",
  "levels": []
}
```

**Difficulty Levels:**
- `easy`: Beginner-friendly, guided exercises
- `medium`: Intermediate, less guidance
- `hard`: Advanced, minimal hints

### Step 2: Create Levels

Each level represents a complete lesson with its own environment and challenges.

```json
{
  "title": "SQL Injection Basics",
  "description": "Learn to identify and exploit SQL injection vulnerabilities",
  "topology": {
    "vms": [
      {
        "name": "web-app",
        "image": "ubuntu-20.04.img",
        "memory": 2048,
        "vcpus": 2
      }
    ]
  },
  "tasks": []
}
```

### Step 3: Add Tasks

Tasks are questions or challenges students must complete.

#### Quiz Task

Automatically graded text answers:

```json
{
  "question": "What is the database administrator's username?",
  "type": "quiz",
  "answer": "admin",
  "hints": [
    "Look for common usernames",
    "Try 'admin' or 'root'",
    "The username is 'admin'"
  ]
}
```

**Features:**
- Case-insensitive matching
- Exact string comparison
- Multiple hints with penalties

#### Action Task

Requires manual verification or scripts:

```json
{
  "question": "Gain root access to the server",
  "type": "action",
  "verification_script": "/opt/check_root.sh",
  "hints": [
    "Check for SUID binaries",
    "Look at sudo permissions"
  ]
}
```

## Training Definition Format

### Complete Example

```json
{
  "id": "web-security-101",
  "title": "Web Security Fundamentals",
  "description": "Introduction to web application security testing",
  "difficulty": "easy",
  "levels": [
    {
      "id": "level-1",
      "title": "Reconnaissance",
      "description": "Learn to gather information about a target",
      "topology": {
        "vms": [
          {
            "name": "target-server",
            "image": "ubuntu-20.04.img",
            "memory": 1024,
            "vcpus": 1
          }
        ]
      },
      "tasks": [
        {
          "id": "task-1",
          "question": "What web server is running on port 80?",
          "type": "quiz",
          "answer": "Apache",
          "hints": [
            "Use nmap to scan the server",
            "Check the HTTP headers"
          ]
        },
        {
          "id": "task-2",
          "question": "What is the server's operating system?",
          "type": "quiz",
          "answer": "Ubuntu",
          "hints": [
            "OS detection tools can help",
            "Look at the SSH banner"
          ]
        }
      ]
    },
    {
      "id": "level-2",
      "title": "SQL Injection",
      "description": "Exploit SQL injection to access the database",
      "topology": {
        "vms": [
          {
            "name": "vulnerable-app",
            "image": "dvwa.qcow2",
            "memory": 2048,
            "vcpus": 2
          }
        ]
      },
      "tasks": [
        {
          "id": "task-1",
          "question": "How many users are in the database?",
          "type": "quiz",
          "answer": "5",
          "hints": [
            "Try SQL injection in the login form",
            "Use UNION SELECT to query user table",
            "SELECT COUNT(*) FROM users"
          ]
        }
      ]
    }
  ]
}
```

### YAML Format

Trainings can also be defined in YAML:

```yaml
title: Web Security Fundamentals
description: Introduction to web application security testing
difficulty: easy
levels:
  - title: Reconnaissance
    description: Learn to gather information about a target
    topology:
      vms:
        - name: target-server
          image: ubuntu-20.04.img
          memory: 1024
          vcpus: 1
    tasks:
      - question: What web server is running on port 80?
        type: quiz
        answer: Apache
        hints:
          - Use nmap to scan the server
          - Check the HTTP headers
```

## Managing Trainings

### Creating via Web Interface

1. Navigate to **Training** tab
2. Click **"Create New Training"**
3. Fill in metadata:
   - Title
   - Description  
   - Difficulty
4. Add levels:
   - Click **"Add Level"**
   - Configure topology
   - Add tasks
5. Save the training

### Creating via File Upload

1. Create a JSON or YAML file
2. Go to **Training** tab
3. Click **"Upload Training"**
4. Select your file
5. Training is imported

### Creating via API

```bash
curl -X POST http://localhost:8001/api/trainings \
  -H "Content-Type: application/json" \
  -d @training.json
```

### Editing Trainings

1. Go to **Training** tab
2. Click on a training
3. Click **"Edit"**
4. Make changes
5. Save

### Deleting Trainings

1. Go to **Training** tab
2. Click on a training
3. Click **"Delete"**
4. Confirm deletion

## Running a Training

### Creating a Training Run

A training run is an instance of a training for specific participants.

**Via Web Interface:**
1. Select a training
2. Click **"Start Training Run"**
3. Enter participant names
4. Click **"Create"**

**Via API:**
```bash
curl -X POST 'http://localhost:8001/api/training-runs?definition_id=web-security-101&participants[]=alice&participants[]=bob'
```

### Training Run Workflow

```
1. Create Run
   ↓
2. Deploy Level 1 VMs
   ↓
3. Students access VMs
   ↓
4. Students solve tasks
   ↓
5. Submit answers
   ↓
6. Auto-grading
   ↓
7. Advance to Level 2 (if correct)
   ↓
8. Repeat until complete
```

### Deploying Level VMs

Before students can work on a level, deploy its VMs:

```bash
POST /api/trainings/{training_id}/levels/{level_idx}/deploy
```

This creates all VMs defined in the level's topology.

### Submitting Answers

Students submit answers via the API or web interface:

```bash
curl -X POST http://localhost:8001/api/training-runs/{run_id}/levels/0/submit \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task-1",
    "answer": "Apache"
  }'
```

**Response if correct:**
```json
{
  "correct": true,
  "message": "Correct! Moving to next task.",
  "score": 100
}
```

**Response if incorrect:**
```json
{
  "correct": false,
  "message": "Incorrect answer. Try again.",
  "attempts_remaining": 2
}
```

### Using Hints

Students can request hints (with score penalty):

```bash
curl -X POST http://localhost:8001/api/training-runs/{run_id}/levels/0/hint \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task-1"
  }'
```

**Response:**
```json
{
  "hint": "Use nmap to scan the server",
  "penalty": 10,
  "remaining_hints": 2
}
```

### Tracking Progress

Get current run state:

```bash
GET /api/training-runs/{run_id}
```

**Response:**
```json
{
  "run_id": "run-abc123",
  "definition_id": "web-security-101",
  "participants": ["alice", "bob"],
  "state": "in_progress",
  "current_level": 1,
  "score": 80,
  "completed_tasks": ["task-1"],
  "hints_used": 1
}
```

### Destroying Level VMs

Clean up VMs when done with a level:

```bash
POST /api/trainings/{training_id}/levels/{level_idx}/destroy
```

## Scoring System

### Base Scoring

- **Correct answer**: +100 points
- **Incorrect answer**: -10 points (optional)
- **Level completion**: +50 bonus points

### Hint Penalties

Each hint deducts points:
- First hint: -10 points
- Second hint: -15 points
- Third hint: -20 points

### Final Score

```
Final Score = Base Points - Hint Penalties - Incorrect Attempts
```

## Advanced Features

### Console Streaming

Training runs can receive real-time console output from VMs:

1. Enable console streaming when deploying
2. Events are sent via WebSocket
3. Monitor student activity
4. Detect task completion automatically

### Event Bus Integration

Training runs subscribe to events:
- VM deployment
- VM destruction
- Console output
- Task completion

```javascript
const ws = new WebSocket('ws://localhost:8001/api/training-runs/run-123/events');
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Event:', data.type, data);
};
```

### Custom Verification Scripts

For action tasks, provide verification scripts:

```bash
#!/bin/bash
# /opt/check_root.sh

if [ "$(id -u)" = "0" ]; then
  echo "SUCCESS"
  exit 0
else
  echo "FAIL"
  exit 1
fi
```

The training system runs the script and checks the exit code:
- Exit 0: Success
- Exit 1+: Failure

## Best Practices

### Training Design

1. **Progressive Difficulty**
   - Start easy, gradually increase complexity
   - Build on previous levels

2. **Clear Instructions**
   - Write clear, unambiguous questions
   - Provide context and objectives

3. **Meaningful Hints**
   - First hint: General direction
   - Second hint: Specific technique
   - Third hint: Almost the answer

4. **Realistic Scenarios**
   - Use real-world examples
   - Avoid contrived situations

5. **Appropriate Scope**
   - 3-5 levels per training
   - 2-4 tasks per level
   - 30-60 minutes per level

### VM Configuration

1. **Resource Allocation**
   - Don't over-allocate resources
   - 1-2 GB RAM for most tasks
   - 1-2 vCPUs sufficient

2. **Image Preparation**
   - Pre-install required tools
   - Configure services to auto-start
   - Test thoroughly before deployment

3. **Network Isolation**
   - Isolate from production networks
   - Use private networks
   - Disable unnecessary services

### Grading

1. **Answer Formats**
   - Accept multiple correct formats
   - Case-insensitive when appropriate
   - Trim whitespace

2. **Partial Credit**
   - Award points for progress
   - Don't penalize exploration

3. **Time Limits**
   - Set reasonable time limits
   - Consider skill level
   - Allow extensions if needed

## Example Training Scenarios

### 1. Basic Linux Security

**Level 1**: File Permissions
- Identify SUID files
- Fix insecure permissions
- Understand chmod/chown

**Level 2**: User Management
- Create users and groups
- Configure sudo access
- Password policies

**Level 3**: Service Hardening
- Disable unnecessary services
- Configure firewall rules
- Secure SSH

### 2. Web Application Security

**Level 1**: Reconnaissance
- Port scanning
- Service enumeration
- Technology fingerprinting

**Level 2**: SQL Injection
- Identify vulnerable parameters
- Extract database contents
- Bypass authentication

**Level 3**: XSS (Cross-Site Scripting)
- Find XSS vulnerabilities
- Craft payloads
- Session hijacking

### 3. Network Security

**Level 1**: Packet Analysis
- Capture traffic with tcpdump
- Analyze with Wireshark
- Identify protocols

**Level 2**: MITM Attack
- ARP spoofing
- Traffic interception
- SSL stripping

**Level 3**: Network Forensics
- Investigate breach
- Extract IOCs
- Timeline reconstruction

## Troubleshooting

### VMs Not Deploying

1. Check image paths are correct
2. Verify sufficient resources
3. Check libvirt connection
4. Review backend logs

### Answers Not Grading

1. Verify answer format matches exactly
2. Check for extra whitespace
3. Review case sensitivity
4. Test with API directly

### Console Not Streaming

1. Ensure VMs are running
2. Check WebSocket connection
3. Verify event bus configuration
4. Review proxy settings

## Storage

Training definitions are stored as JSON files:
```
backend/data/trainings/
├── web-security-101.json
├── linux-basics.json
└── network-forensics.json
```

Training runs are stored as JSON files:
```
backend/training_runs/
├── run-abc123.json
├── run-def456.json
└── run-ghi789.json
```

## Future Enhancements

Planned features:
- [ ] Leaderboards and rankings
- [ ] Team-based training runs
- [ ] Automated report generation
- [ ] Integration with LMS platforms
- [ ] Video walkthroughs
- [ ] Achievement badges
- [ ] Real-time collaboration
- [ ] Instructor dashboard

## See Also

- [User Guide](User-Guide.md) - Basic platform usage
- [API Reference](API-Reference.md) - API endpoints
- [Topology Builder](Topology-Builder.md) - Creating topologies
