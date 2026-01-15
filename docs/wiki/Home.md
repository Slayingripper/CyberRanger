# CyberRanger Wiki

Welcome to the **CyberRanger** documentation! CyberRanger is a lightweight, scalable Cyber Range platform built for cybersecurity training, penetration testing practice, and security research.

## Quick Links

- [Installation & Setup](Installation-and-Setup.md)
- [User Guide](User-Guide.md)
- [Architecture](Architecture.md)
- [API Reference](API-Reference.md)
- [Training System](Training-System.md)
- [Topology Builder](Topology-Builder.md)
- [Troubleshooting](Troubleshooting.md)
- [Contributing](Contributing.md)

## What is CyberRanger?

CyberRanger is a comprehensive cyber range platform that enables:

- **Virtual Machine Management**: Create, manage, and control VMs using QEMU/KVM with an intuitive web interface
- **Browser-Based Access**: Access VM consoles directly in your browser using NoVNC
- **Scenario Deployment**: Deploy pre-configured security scenarios with YAML definitions
- **Training System**: Build and deploy multi-level cybersecurity training courses
- **Topology Builder**: Design custom network topologies with a visual drag-and-drop interface
- **Image Management**: Automated download and management of OS images
- **Network Isolation**: Create isolated networks for secure training environments

## Key Features

### 🖥️ **Backend** 
- Python FastAPI framework
- Libvirt integration for KVM/QEMU
- WebSocket support for real-time updates
- RESTful API for all operations

### 🎨 **Frontend**
- React with Vite for fast development
- Tailwind CSS for modern styling
- NoVNC integration for in-browser console access
- React Flow for topology visualization

### 🔧 **Core Capabilities**
- Multi-VM scenario deployment
- Cloud-init support for automated configuration
- Network topology builder with visual editor
- Training course system with progress tracking
- Image download and management
- Range mapping for network discovery

## Use Cases

- **Cybersecurity Training**: Create hands-on training environments for students
- **Penetration Testing Practice**: Deploy vulnerable VMs for ethical hacking practice
- **Red Team/Blue Team Exercises**: Set up attack/defend scenarios
- **Security Research**: Build isolated lab environments
- **CTF Competitions**: Host Capture The Flag events
- **Network Simulation**: Test network configurations and security controls

## Getting Started

1. Check the [Installation & Setup](Installation-and-Setup.md) guide to get CyberRanger running
2. Read the [User Guide](User-Guide.md) to learn how to use the platform
3. Explore the [Topology Builder](Topology-Builder.md) to create custom scenarios
4. Learn about the [Training System](Training-System.md) for creating educational content

## Community & Support

- **Issues**: Report bugs or request features on [GitHub Issues](https://github.com/Slayingripper/CyberRanger/issues)
- **Contributions**: See our [Contributing Guide](Contributing.md)

## License

This project is open source. Check the repository for license details.
