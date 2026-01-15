# Contributing

Thank you for your interest in contributing to CyberRanger! This guide will help you get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Reporting Bugs](#reporting-bugs)
- [Feature Requests](#feature-requests)

## Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inclusive environment for all contributors.

### Expected Behavior

- Be respectful and considerate
- Use welcoming and inclusive language
- Accept constructive criticism gracefully
- Focus on what's best for the community
- Show empathy towards others

### Unacceptable Behavior

- Harassment or discrimination
- Trolling or insulting comments
- Publishing others' private information
- Any conduct that could be considered inappropriate

## Getting Started

### Prerequisites

Before contributing, ensure you have:

- Git installed
- Docker and Docker Compose
- Basic knowledge of Python and JavaScript
- Understanding of virtualization concepts
- Familiarity with Git workflows

### Fork and Clone

1. **Fork the repository** on GitHub
2. **Clone your fork:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/CyberRanger.git
   cd CyberRanger
   ```

3. **Add upstream remote:**
   ```bash
   git remote add upstream https://github.com/Slayingripper/CyberRanger.git
   ```

4. **Verify remotes:**
   ```bash
   git remote -v
   ```

## Development Setup

### Backend Development

1. **Install Python dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Run backend locally (optional):**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
   ```

3. **Run tests:**
   ```bash
   pytest tests/
   ```

### Frontend Development

1. **Install Node dependencies:**
   ```bash
   cd frontend
   npm install
   ```

2. **Run development server:**
   ```bash
   npm run dev
   ```

3. **Build for production:**
   ```bash
   npm run build
   ```

4. **Lint code:**
   ```bash
   npm run lint
   ```

### Using Docker Compose

For full-stack development:

```bash
docker-compose up --build
```

This runs both backend and frontend with hot-reload enabled.

## How to Contribute

### Types of Contributions

We welcome various types of contributions:

1. **Bug Fixes**
   - Fix reported issues
   - Improve error handling
   - Enhance stability

2. **Features**
   - New functionality
   - UI improvements
   - API enhancements

3. **Documentation**
   - Wiki updates
   - Code comments
   - API documentation
   - Tutorials

4. **Testing**
   - Unit tests
   - Integration tests
   - Test coverage improvements

5. **Performance**
   - Optimization
   - Resource usage reduction
   - Speed improvements

### Contribution Workflow

1. **Choose an issue** from GitHub Issues or create a new one
2. **Comment** on the issue to indicate you're working on it
3. **Create a branch** for your work
4. **Make changes** following our coding standards
5. **Write tests** for new functionality
6. **Commit** with clear, descriptive messages
7. **Push** to your fork
8. **Open a Pull Request** to the main repository

### Branch Naming

Use descriptive branch names:

- `feature/add-network-mapper`
- `fix/vm-creation-error`
- `docs/update-api-reference`
- `refactor/simplify-topology-deployment`

## Coding Standards

### Python (Backend)

**Style Guide:** Follow PEP 8

**Formatting:**
```python
# Good
def create_vm(name: str, memory_mb: int, vcpus: int) -> dict:
    """Create a virtual machine.
    
    Args:
        name: VM name
        memory_mb: RAM in megabytes
        vcpus: Number of virtual CPUs
        
    Returns:
        Dictionary with VM details
    """
    result = {
        "status": "success",
        "name": name,
    }
    return result
```

**Best Practices:**
- Use type hints
- Write docstrings for functions and classes
- Keep functions focused and small
- Handle exceptions appropriately
- Use meaningful variable names

**Imports:**
```python
# Standard library imports
import os
import sys

# Third-party imports
from fastapi import APIRouter, HTTPException
import libvirt

# Local imports
from app.core.vm_manager import vm_manager
```

### JavaScript/React (Frontend)

**Style Guide:** Standard JavaScript style

**Formatting:**
```javascript
// Good
function CreateVMModal({ onClose, onCreated }) {
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    
    try {
      await createVM({ name });
      onCreated();
    } catch (error) {
      console.error('Failed to create VM:', error);
    } finally {
      setLoading(false);
    }
  };
  
  return (
    // JSX here
  );
}
```

**Best Practices:**
- Use functional components with hooks
- PropTypes or TypeScript for type checking
- Descriptive component names
- Extract reusable logic into hooks
- Keep components focused

**File Organization:**
```
components/
├── VirtualMachines/
│   ├── VMList.jsx
│   ├── VMCard.jsx
│   └── CreateVMModal.jsx
├── Training/
│   ├── TrainingList.jsx
│   └── TrainingEditor.jsx
└── common/
    ├── Button.jsx
    └── Modal.jsx
```

### Git Commit Messages

Follow conventional commit format:

```
type(scope): brief description

Longer description if needed.

Fixes #123
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code formatting (no logic change)
- `refactor`: Code restructuring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(vm): add cloud-init support for VMs

fix(frontend): resolve VNC console connection issue

docs(wiki): update installation guide

test(backend): add tests for VM creation
```

## Testing

### Backend Tests

**Running Tests:**
```bash
cd backend
pytest
```

**Writing Tests:**
```python
# tests/test_vm_manager.py
import pytest
from app.core.vm_manager import vm_manager

def test_create_vm():
    """Test VM creation."""
    result = vm_manager.create_vm(
        name="test-vm",
        memory_mb=2048,
        vcpus=2,
        iso_path="/app/images/test.iso"
    )
    assert result["status"] == "success"
    assert result["name"] == "test-vm"
```

**Test Coverage:**
```bash
pytest --cov=app tests/
```

### Frontend Tests

**Running Tests:**
```bash
cd frontend
npm test
```

**Writing Tests:**
```javascript
// src/components/VMCard.test.jsx
import { render, screen } from '@testing-library/react';
import VMCard from './VMCard';

test('renders VM name', () => {
  const vm = { name: 'test-vm', state: 1 };
  render(<VMCard vm={vm} />);
  expect(screen.getByText('test-vm')).toBeInTheDocument();
});
```

### Integration Tests

Test complete workflows:

```python
def test_full_topology_deployment():
    """Test deploying a complete topology."""
    topology = {
        "nodes": [...],
        "edges": [...]
    }
    
    # Deploy topology
    result = deploy_topology(topology)
    assert result["status"] == "deployment_processed"
    
    # Verify VMs created
    vms = list_vms()
    assert len(vms) == len(topology["nodes"])
    
    # Cleanup
    for vm in vms:
        delete_vm(vm["name"])
```

## Pull Request Process

### Before Submitting

1. **Update your branch:**
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Run tests:**
   ```bash
   # Backend
   cd backend && pytest
   
   # Frontend
   cd frontend && npm test
   ```

3. **Lint code:**
   ```bash
   # Backend
   flake8 backend/app/
   
   # Frontend
   npm run lint
   ```

4. **Update documentation** if needed

### Submitting a PR

1. **Push to your fork:**
   ```bash
   git push origin feature/your-feature
   ```

2. **Open Pull Request** on GitHub

3. **Fill in the template:**
   - Description of changes
   - Related issues
   - Testing performed
   - Screenshots (if UI changes)

### PR Template

```markdown
## Description
Brief description of changes

## Related Issue
Fixes #123

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing completed

## Screenshots
(if applicable)

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] No new warnings generated
```

### Review Process

1. **Automated checks** run on your PR
2. **Maintainers review** your code
3. **Address feedback** if requested
4. **Approval** from maintainer(s)
5. **Merge** into main branch

## Reporting Bugs

### Before Reporting

1. **Search existing issues** to avoid duplicates
2. **Test with latest version**
3. **Gather information:**
   - System details
   - Steps to reproduce
   - Expected vs actual behavior
   - Logs and error messages

### Bug Report Template

```markdown
## Bug Description
Clear description of the bug

## Steps to Reproduce
1. Go to '...'
2. Click on '...'
3. See error

## Expected Behavior
What should happen

## Actual Behavior
What actually happens

## Environment
- OS: [e.g., Ubuntu 22.04]
- Docker version: [e.g., 24.0.0]
- CyberRanger version: [e.g., 1.0.0]

## Logs
```
Paste relevant logs here
```

## Screenshots
(if applicable)
```

## Feature Requests

### Proposing Features

1. **Check existing issues** for similar requests
2. **Describe the problem** your feature solves
3. **Explain your solution**
4. **Consider alternatives**
5. **Discuss impact** on existing functionality

### Feature Request Template

```markdown
## Problem Statement
Describe the problem this feature solves

## Proposed Solution
Detailed description of your proposed solution

## Alternatives Considered
Other solutions you've thought about

## Additional Context
Any other relevant information

## Benefits
- Benefit 1
- Benefit 2
```

## Development Guidelines

### Architecture Decisions

When making significant changes:

1. **Discuss first** in an issue or discussion
2. **Consider backwards compatibility**
3. **Document the decision**
4. **Update architecture docs** if needed

### Security

- **Never commit secrets** (passwords, API keys)
- **Validate all inputs**
- **Follow security best practices**
- **Report security issues privately**

### Performance

- **Benchmark** performance-critical code
- **Optimize** where it matters
- **Document** performance considerations
- **Test** with realistic loads

### Accessibility

- **Semantic HTML** in frontend
- **ARIA labels** where needed
- **Keyboard navigation** support
- **Color contrast** standards

## Communication

### Channels

- **GitHub Issues**: Bug reports, feature requests
- **Pull Requests**: Code contributions
- **Discussions**: General questions, ideas

### Response Times

- Issues: Acknowledged within 48 hours
- PRs: Initial review within 1 week
- Security issues: Within 24 hours

## Recognition

Contributors are recognized through:
- GitHub contributors list
- Release notes
- Community acknowledgments

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

## Questions?

If you have questions:
1. Check the [Wiki](Home.md)
2. Search [Issues](https://github.com/Slayingripper/CyberRanger/issues)
3. Open a new issue with the "question" label

## Thank You!

Your contributions make CyberRanger better for everyone. We appreciate your time and effort!

---

## Quick Reference

### Common Commands

```bash
# Update from upstream
git fetch upstream
git merge upstream/main

# Create feature branch
git checkout -b feature/my-feature

# Run all tests
cd backend && pytest && cd ../frontend && npm test

# Commit changes
git add .
git commit -m "feat(scope): description"

# Push to fork
git push origin feature/my-feature
```

### Useful Links

- [Main Repository](https://github.com/Slayingripper/CyberRanger)
- [Issues](https://github.com/Slayingripper/CyberRanger/issues)
- [Pull Requests](https://github.com/Slayingripper/CyberRanger/pulls)
- [Wiki Home](Home.md)
