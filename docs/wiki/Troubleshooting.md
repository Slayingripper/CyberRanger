# Troubleshooting

Common issues and solutions for CyberRanger.

## Installation Issues

### Permission Denied - Libvirt Socket

**Symptom:**
```
Permission denied: '/var/run/libvirt/libvirt-sock'
```

**Cause:** Docker container can't access libvirt socket.

**Solutions:**

1. **Add user to libvirt group:**
   ```bash
   sudo usermod -aG libvirt $USER
   # Log out and back in
   ```

2. **Run with sudo (not recommended for production):**
   ```bash
   sudo docker-compose up
   ```

3. **Fix socket permissions:**
   ```bash
   sudo chmod 666 /var/run/libvirt/libvirt-sock
   ```

4. **Check libvirt is running:**
   ```bash
   sudo systemctl status libvirtd
   sudo systemctl start libvirtd
   ```

### Docker Daemon Not Running

**Symptom:**
```
Cannot connect to the Docker daemon
```

**Solution:**
```bash
sudo systemctl start docker
sudo systemctl enable docker
```

### Port Already in Use

**Symptom:**
```
Error: bind: address already in use
```

**Cause:** Port 8001 or 5173 is occupied.

**Solution:**

1. **Find process using port:**
   ```bash
   sudo lsof -i :8001
   sudo lsof -i :5173
   ```

2. **Kill the process:**
   ```bash
   kill -9 <PID>
   ```

3. **Or change ports in docker-compose.yml:**
   ```yaml
   environment:
     - VITE_API_URL=http://localhost:8002/api
   command: sh -c "uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload"
   ```

### KVM Not Available

**Symptom:**
```
kvm: command not found
```

**Solution:**
```bash
# Check CPU virtualization support
egrep -c '(vmx|svm)' /proc/cpuinfo

# Install KVM
sudo apt update
sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils

# Enable virtualization in BIOS if needed
```

## VM Management Issues

### VM Creation Fails

**Symptom:**
```
Failed to create VM: Image not found
```

**Solutions:**

1. **Check image path:**
   ```bash
   ls -la images/
   ```

2. **Verify image exists:**
   - Images must be in `./images/` directory
   - Check filename matches exactly

3. **Download missing image:**
   ```bash
   cd images
   wget https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img
   ```

4. **Check disk space:**
   ```bash
   df -h
   ```

### VM Won't Start

**Symptom:** VM state remains "Stopped" after clicking Start.

**Solutions:**

1. **Check backend logs:**
   ```bash
   docker logs cyberrange-backend
   ```

2. **Verify libvirt connection:**
   ```bash
   virsh list --all
   ```

3. **Check VM definition:**
   ```bash
   virsh dumpxml <vm-name>
   ```

4. **Resource availability:**
   ```bash
   free -h  # Check RAM
   nproc    # Check CPUs
   ```

5. **Manually start VM:**
   ```bash
   virsh start <vm-name>
   ```

### VNC Console Not Working

**Symptom:** Black screen or "Connection failed" in NoVNC.

**Solutions:**

1. **Verify VM is running:**
   ```bash
   virsh list
   ```

2. **Check VNC port:**
   ```bash
   virsh vncdisplay <vm-name>
   ```

3. **Test VNC connection:**
   ```bash
   vncviewer localhost:5900
   ```

4. **Check NoVNC ports are open:**
   ```bash
   sudo netstat -tlnp | grep 60
   ```

5. **Restart the VM:**
   ```bash
   virsh destroy <vm-name>
   virsh start <vm-name>
   ```

### VM Deletion Fails

**Symptom:** "VM could not be deleted"

**Solutions:**

1. **Stop VM first:**
   ```bash
   virsh destroy <vm-name>
   ```

2. **Force undefine:**
   ```bash
   virsh undefine <vm-name> --remove-all-storage
   ```

3. **Manual cleanup:**
   ```bash
   # Remove disk files
   rm -f disks/<vm-name>*.qcow2
   
   # Remove cloud-init ISOs
   rm -f disks/<vm-name>-cloud-init.iso
   ```

## Network Issues

### Network Creation Fails

**Symptom:** "Failed to create network"

**Solutions:**

1. **Check existing networks:**
   ```bash
   virsh net-list --all
   ```

2. **Check for IP conflicts:**
   ```bash
   ip addr show
   ```

3. **Destroy conflicting network:**
   ```bash
   virsh net-destroy <network-name>
   virsh net-undefine <network-name>
   ```

4. **Check bridge availability:**
   ```bash
   brctl show
   ```

### VMs Can't Communicate

**Symptom:** Ping between VMs fails.

**Solutions:**

1. **Verify same network:**
   - Check topology connections
   - Ensure nodes are linked with edges

2. **Check network is active:**
   ```bash
   virsh net-list
   ```

3. **Check VM network interfaces:**
   ```bash
   virsh domiflist <vm-name>
   ```

4. **Verify DHCP (if NAT network):**
   ```bash
   virsh net-dhcp-leases <network-name>
   ```

5. **Check firewall rules:**
   ```bash
   sudo iptables -L -n -v
   ```

### No Internet Access in VM

**Symptom:** VM can't reach internet.

**Solutions:**

1. **Verify NAT network:**
   ```bash
   virsh net-dumpxml <network-name>
   # Should show <forward mode='nat'/>
   ```

2. **Check host internet:**
   ```bash
   ping -c 4 8.8.8.8
   ```

3. **Enable IP forwarding:**
   ```bash
   sudo sysctl -w net.ipv4.ip_forward=1
   ```

4. **Check iptables NAT:**
   ```bash
   sudo iptables -t nat -L -n -v
   ```

## Image Management Issues

### Image Download Fails

**Symptom:** "Failed to download image"

**Solutions:**

1. **Check URL is accessible:**
   ```bash
   curl -I <image-url>
   ```

2. **Verify disk space:**
   ```bash
   df -h images/
   ```

3. **Download manually:**
   ```bash
   cd images
   wget <image-url>
   ```

4. **Check proxy settings:**
   ```bash
   echo $http_proxy
   echo $https_proxy
   ```

### Image Extraction Fails

**Symptom:** "Failed to extract image"

**Solutions:**

1. **Check compression tools:**
   ```bash
   which gunzip bunzip2 7z
   ```

2. **Install missing tools:**
   ```bash
   sudo apt install gzip bzip2 p7zip-full
   ```

3. **Extract manually:**
   ```bash
   cd images
   gunzip image.img.gz
   # or
   bunzip2 image.img.bz2
   # or
   7z x image.img.7z
   ```

4. **Verify downloaded file:**
   ```bash
   file image.img.gz
   md5sum image.img.gz
   ```

## Frontend Issues

### Web Interface Not Loading

**Symptom:** Browser shows "Connection refused"

**Solutions:**

1. **Check frontend is running:**
   ```bash
   docker logs cyberrange-frontend
   ```

2. **Verify port 5173:**
   ```bash
   sudo netstat -tlnp | grep 5173
   ```

3. **Restart frontend:**
   ```bash
   docker-compose restart frontend
   ```

4. **Check browser console:**
   - Open DevTools (F12)
   - Look for JavaScript errors

5. **Clear browser cache:**
   - Hard refresh: Ctrl+Shift+R

### API Connection Errors

**Symptom:** "Network Error" or "Failed to fetch"

**Solutions:**

1. **Check API URL:**
   - Should be `http://localhost:8001/api`
   - Verify in frontend environment

2. **Test API directly:**
   ```bash
   curl http://localhost:8001/api/vms
   ```

3. **Check CORS settings:**
   - Review backend CORS configuration
   - Check browser console for CORS errors

4. **Verify backend is running:**
   ```bash
   docker logs cyberrange-backend
   ```

### WebSocket Connection Fails

**Symptom:** "WebSocket connection failed"

**Solutions:**

1. **Check WebSocket support:**
   ```bash
   curl -i -N \
     -H "Connection: Upgrade" \
     -H "Upgrade: websocket" \
     http://localhost:8001/api/proxy/vm-name
   ```

2. **Verify proxy is running:**
   ```bash
   ps aux | grep websockify
   ```

3. **Check firewall:**
   ```bash
   sudo ufw status
   ```

## Performance Issues

### Slow VM Performance

**Symptom:** VMs are laggy or unresponsive.

**Solutions:**

1. **Check host resources:**
   ```bash
   top
   free -h
   iostat
   ```

2. **Reduce VM allocations:**
   - Lower memory/CPU per VM
   - Shut down unused VMs

3. **Enable KVM acceleration:**
   - Verify in BIOS
   - Check `kvm-ok` output

4. **Use VirtIO drivers:**
   - Better I/O performance
   - Included in most modern images

### High Memory Usage

**Symptom:** Host running out of RAM.

**Solutions:**

1. **Check VM memory:**
   ```bash
   virsh dominfo <vm-name>
   ```

2. **Stop unnecessary VMs:**
   ```bash
   virsh list
   virsh shutdown <vm-name>
   ```

3. **Reduce VM RAM:**
   - Lower memory allocation
   - 1-2 GB sufficient for most tasks

4. **Enable memory ballooning:**
   - Automatic memory adjustment
   - Built into VirtIO

### Disk Space Issues

**Symptom:** "No space left on device"

**Solutions:**

1. **Check disk usage:**
   ```bash
   df -h
   du -sh images/ disks/
   ```

2. **Clean up old VMs:**
   ```bash
   # List all domains
   virsh list --all
   
   # Remove unused VMs
   virsh undefine <vm-name> --remove-all-storage
   ```

3. **Remove old images:**
   ```bash
   cd images
   rm old-image.qcow2
   ```

4. **Compress images:**
   ```bash
   qemu-img convert -O qcow2 -c input.img output.qcow2
   ```

## Deployment Issues

### Topology Deployment Hangs

**Symptom:** Deployment never completes.

**Solutions:**

1. **Check job status:**
   ```bash
   curl http://localhost:8001/api/topology/deploy-jobs/<job-id>
   ```

2. **Review backend logs:**
   ```bash
   docker logs -f cyberrange-backend
   ```

3. **Verify image downloads:**
   - Check network connectivity
   - Verify URLs are accessible

4. **Restart backend:**
   ```bash
   docker-compose restart backend
   ```

### Some Nodes Fail to Deploy

**Symptom:** Some VMs created, others failed.

**Solutions:**

1. **Check error messages:**
   - Review deployment results
   - Check backend logs

2. **Verify image availability:**
   ```bash
   ls -la images/<image-name>
   ```

3. **Check resource limits:**
   - Ensure enough RAM
   - Ensure enough disk space

4. **Deploy failed nodes individually:**
   - Note which nodes failed
   - Create them manually
   - Debug specific issues

## Training Issues

### Training Won't Load

**Symptom:** Training list is empty or error loading.

**Solutions:**

1. **Check training directory:**
   ```bash
   ls -la backend/data/trainings/
   ```

2. **Verify JSON format:**
   ```bash
   cat backend/data/trainings/training-id.json | jq .
   ```

3. **Check file permissions:**
   ```bash
   chmod 644 backend/data/trainings/*.json
   ```

### Answer Not Accepted

**Symptom:** Correct answer marked as incorrect.

**Solutions:**

1. **Check answer format:**
   - Remove extra whitespace
   - Check case sensitivity
   - Verify exact match

2. **Test with API:**
   ```bash
   curl -X POST http://localhost:8001/api/training-runs/<run-id>/levels/0/submit \
     -H "Content-Type: application/json" \
     -d '{"task_id": "task-1", "answer": "test"}'
   ```

3. **Review training definition:**
   - Check expected answer
   - Verify task type is "quiz"

## Logging & Debugging

### Enable Debug Logging

**Backend:**
```python
# app/main.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

**Frontend:**
```javascript
// Enable verbose logging
localStorage.debug = '*';
```

### View Container Logs

```bash
# Backend logs
docker logs -f cyberrange-backend

# Frontend logs
docker logs -f cyberrange-frontend

# All logs
docker-compose logs -f
```

### Check Libvirt Logs

```bash
# System logs
journalctl -u libvirtd -f

# VM logs
virsh console <vm-name>

# QEMU logs
tail -f /var/log/libvirt/qemu/<vm-name>.log
```

### Test API Endpoints

```bash
# List VMs
curl http://localhost:8001/api/vms

# Get specific VM
curl http://localhost:8001/api/vms/<vm-name>

# List images
curl http://localhost:8001/api/images

# Check health
curl http://localhost:8001/
```

## Getting Help

### Collect Information

Before reporting issues:

1. **System information:**
   ```bash
   uname -a
   docker --version
   virsh --version
   ```

2. **Container status:**
   ```bash
   docker-compose ps
   ```

3. **Logs:**
   ```bash
   docker-compose logs > logs.txt
   ```

4. **Network info:**
   ```bash
   virsh net-list --all
   ip addr show
   ```

### Report Issues

Include in your report:
- Description of the problem
- Steps to reproduce
- Expected vs actual behavior
- System information
- Relevant logs
- Screenshots if applicable

### Community Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/Slayingripper/CyberRanger/issues)
- **Documentation**: Check other wiki pages
- **Discussions**: GitHub Discussions (if enabled)

## Preventive Maintenance

### Regular Tasks

**Daily:**
- Monitor disk space
- Check VM resource usage
- Review backend logs

**Weekly:**
- Clean up unused VMs
- Update images
- Check for updates

**Monthly:**
- System updates
- Security patches
- Backup configurations

### Backup Strategy

**What to backup:**
- Training definitions (`backend/data/trainings/`)
- Training runs (`backend/training_runs/`)
- Custom images (`images/`)
- Topology designs
- Configuration files

**Backup command:**
```bash
tar -czf cyberrange-backup-$(date +%Y%m%d).tar.gz \
  backend/data/trainings/ \
  backend/training_runs/ \
  images/ \
  scenarios/
```

### Health Checks

**System health:**
```bash
#!/bin/bash
# health-check.sh

# Check Docker
docker ps | grep cyberrange || echo "Docker containers not running"

# Check disk space
df -h | grep -E '^/dev/' | awk '$5+0 > 80 {print "WARNING: "$0}'

# Check libvirt
systemctl is-active libvirtd || echo "libvirtd not running"

# Check VM count
virsh list --all | wc -l
```

## Common Error Messages

### "Domain already exists"

**Fix:**
```bash
virsh undefine <vm-name>
```

### "Network already exists"

**Fix:**
```bash
virsh net-destroy <network-name>
virsh net-undefine <network-name>
```

### "Operation not permitted"

**Fix:**
```bash
# Check user permissions
groups

# Add to required groups
sudo usermod -aG libvirt,kvm $USER
```

### "No space left on device"

**Fix:**
```bash
# Clean up old VMs
virsh list --all
virsh undefine <old-vm> --remove-all-storage

# Remove old images
rm images/old-*.qcow2
```

### "Connection refused"

**Fix:**
```bash
# Check service is running
docker-compose ps

# Restart services
docker-compose restart
```

## See Also

- [Installation & Setup](Installation-and-Setup.md) - Initial setup guide
- [User Guide](User-Guide.md) - Platform usage
- [Architecture](Architecture.md) - Technical details
