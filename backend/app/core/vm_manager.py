import libvirt
import sys
import xml.etree.ElementTree as ET
import uuid
import os
import subprocess
import json
from typing import List, Dict, Optional, Any
import ipaddress
import xml.etree.ElementTree as ET

# Determine working directory
# If running in Docker, /app should exist.
# If running locally, use backend/data.
if os.path.exists("/app"):
    WORK_DIR = "/app"
else:
    # backend/app/core/vm_manager.py -> backend/app/core -> backend/app -> backend
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    WORK_DIR = os.path.join(BASE_DIR, "data")

HOST_WORK_DIR = os.environ.get("HOST_WORK_DIR", WORK_DIR)

# Ensure directories exist
os.makedirs(os.path.join(WORK_DIR, "images"), exist_ok=True)
os.makedirs(os.path.join(WORK_DIR, "disks"), exist_ok=True)

class VMManager:
    def __init__(self, uri="qemu:///system"):
        self.uri = uri
        self.conn = None
        self.proxies = {} # vm_name -> {'proc': Popen, 'port': int, 'vnc_port': str}

    def connect(self):
        try:
            self.conn = libvirt.open(self.uri)
        except libvirt.libvirtError as e:
            print(f"Failed to open connection to {self.uri}: {e}", file=sys.stderr)
            return False
        return True

    def disconnect(self):
        if self.conn:
            self.conn.close()
        # Cleanup proxies
        for vm_name, info in self.proxies.items():
            if info['proc'].poll() is None:
                info['proc'].terminate()
        self.proxies = {}

    def ensure_vnc_proxy(self, vm_name, vnc_port):
        if not vnc_port:
            return None
            
        ws_port = int(vnc_port) + 1000
        
        # Check if already running
        if vm_name in self.proxies:
            proc_info = self.proxies[vm_name]
            if proc_info['proc'].poll() is None:
                # Still running
                if proc_info['vnc_port'] == vnc_port:
                    return ws_port
                else:
                    # VNC port changed (restart?), kill old proxy
                    proc_info['proc'].terminate()
            
        # Start new proxy
        print(f"Starting VNC proxy for {vm_name}: {vnc_port} -> {ws_port}")
        try:
            # Run in background
            # Using python -m websockify to ensure we use the installed package
            cmd = [sys.executable, "-m", "websockify", f"0.0.0.0:{ws_port}", f"127.0.0.1:{vnc_port}"]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.proxies[vm_name] = {
                'proc': proc,
                'port': ws_port,
                'vnc_port': vnc_port
            }
            return ws_port
        except Exception as e:
            print(f"Failed to start websockify: {e}")
            return None

    def list_domains(self) -> List[Dict]:
        if not self.conn:
            self.connect()
        
        domains = []
        try:
            # List active domains
            for domain_id in self.conn.listDomainsID():
                dom = self.conn.lookupByID(domain_id)
                domains.append(self._get_domain_info(dom))
            
            # List inactive domains
            for name in self.conn.listDefinedDomains():
                dom = self.conn.lookupByName(name)
                domains.append(self._get_domain_info(dom))
        except libvirt.libvirtError:
            pass
            
        return domains

    def list_domains_with_interfaces(self) -> List[Dict[str, Any]]:
        """Return VMs with network interface details (network name, MAC, IPs).

        Uses libvirt interfaceAddresses with DHCP lease source; falls back to XML parsing for network name.
        """
        if not self.conn:
            self.connect()

        results: List[Dict[str, Any]] = []

        try:
            domain_names = []
            for domain_id in self.conn.listDomainsID():
                dom = self.conn.lookupByID(domain_id)
                domain_names.append(dom.name())
            for name in self.conn.listDefinedDomains():
                domain_names.append(name)

            for name in domain_names:
                try:
                    dom = self.conn.lookupByName(name)
                except libvirt.libvirtError:
                    continue

                iface_info = []
                try:
                    addrs = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE, 0)
                except libvirt.libvirtError:
                    addrs = {}

                # Build MAC->network map from XML
                try:
                    xml_desc = dom.XMLDesc(0)
                    root = ET.fromstring(xml_desc)
                    mac_to_net: Dict[str, str] = {}
                    for iface in root.findall("./devices/interface"):
                        mac_el = iface.find("mac")
                        src_el = iface.find("source")
                        if mac_el is not None and src_el is not None:
                            mac = mac_el.get("address")
                            net = src_el.get("network") or src_el.get("bridge")
                            if mac and net:
                                mac_to_net[mac.lower()] = net
                except Exception:
                    mac_to_net = {}

                for ifname, data in (addrs or {}).items():
                    mac = data.get("hwaddr")
                    addrs_list = []
                    for a in data.get("addrs", []) or []:
                        ip = a.get("addr")
                        if ip:
                            addrs_list.append(ip)
                    iface_info.append(
                        {
                            "name": ifname,
                            "mac": mac,
                            "network": mac_to_net.get(mac.lower()) if mac else None,
                            "ips": addrs_list,
                        }
                    )

                results.append({"name": name, "interfaces": iface_info})

        except libvirt.libvirtError:
            pass

        return results

    def _get_domain_info(self, dom):
        state, maxmem, mem, cpus, cput = dom.info()
        # Parse XML to get VNC port
        try:
            xml_desc = dom.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            
            graphics = root.find("./devices/graphics")
            vnc_port = None
            if graphics is not None and graphics.get('type') == 'vnc':
                vnc_port = graphics.get('port')
        except:
            vnc_port = None

        websocket_port = None
        if state == 1 and vnc_port and vnc_port != '-1':
            websocket_port = self.ensure_vnc_proxy(dom.name(), vnc_port)

        return {
            "id": dom.ID(),
            "name": dom.name(),
            "uuid": dom.UUIDString(),
            "state": state, # 1=running, 5=shutoff
            "memory": mem,
            "vcpus": cpus,
            "vnc_port": vnc_port,
            "websocket_port": websocket_port
        }

    def create_cloud_init_iso(self, vm_name: str, user_data: str, meta_data: str):
        # Create a temporary directory for this VM's cloud-init files
        config_dir = os.path.join(WORK_DIR, "disks", f"{vm_name}_cidata")
        os.makedirs(config_dir, exist_ok=True)
        
        with open(os.path.join(config_dir, "user-data"), "w") as f:
            f.write(user_data)
        with open(os.path.join(config_dir, "meta-data"), "w") as f:
            f.write(meta_data)
            
        iso_path = os.path.join(WORK_DIR, "disks", f"{vm_name}_cidata.iso")
        host_iso_path = os.path.join(HOST_WORK_DIR, "disks", f"{vm_name}_cidata.iso")
        
        # Generate ISO
        cmd = [
            "genisoimage",
            "-output", iso_path,
            "-volid", "cidata",
            "-joliet",
            "-rock",
            config_dir
        ]
        subprocess.run(cmd, check=True)
        
        # Cleanup config dir
        # shutil.rmtree(config_dir) 
        
        return host_iso_path

    def create_vm(
        self,
        name: str,
        memory_mb: int,
        vcpus: int,
        image_path: Optional[str] = None,
        iso_path: Optional[str] = None,
        cloud_init: Optional[dict] = None,
        network_name: str = "default",
        network_names: Optional[List[str]] = None,
    ):
        if not self.conn:
            self.connect()

        # If a domain already exists with this name, remove it so redeploy works.
        try:
            existing = self.conn.lookupByName(name)
            if existing is not None:
                try:
                    if existing.isActive():
                        existing.destroy()
                finally:
                    existing.undefine()
        except libvirt.libvirtError:
            pass

        # Remove stale disk/cidata artifacts from previous runs (best-effort)
        stale_disk = os.path.join(WORK_DIR, "disks", f"{name}.qcow2")
        stale_cidata_iso = os.path.join(WORK_DIR, "disks", f"{name}_cidata.iso")
        if os.path.exists(stale_disk):
            try:
                os.remove(stale_disk)
            except Exception:
                pass
        if os.path.exists(stale_cidata_iso):
            try:
                os.remove(stale_cidata_iso)
            except Exception:
                pass

        # Determine disk path
        # If image_path is provided, use it (assuming it's a full path on host)
        # If iso_path is provided, we create a new disk and attach ISO
        
        disk_xml = ""
        boot_dev = "hd"
        machine_type = "pc-q35-6.2"
        
        if iso_path:
            # Many installer ISOs are more reliable under i440fx + IDE CDROM.
            machine_type = "pc-i440fx-6.2"

            # Create new disk
            disk_filename = f"{name}.qcow2"
            container_disk_path = os.path.join(WORK_DIR, "disks", disk_filename)
            host_disk_path = os.path.join(HOST_WORK_DIR, "disks", disk_filename)
            
            # Create disk for ISO installs.
            # Security Onion needs much more storage than typical Linux installers.
            disk_size = "20G"
            try:
                iso_base = os.path.basename(iso_path).lower()
                if "securityonion" in iso_base or "security-onion" in iso_base:
                    disk_size = "200G"
            except Exception:
                pass

            subprocess.run(["qemu-img", "create", "-f", "qcow2", container_disk_path, disk_size], check=True)
            
            disk_xml = f"""
            <disk type='file' device='disk'>
              <driver name='qemu' type='qcow2'/>
              <source file='{host_disk_path}'/>
              <target dev='vda' bus='virtio'/>
            </disk>
            <disk type='file' device='cdrom'>
              <driver name='qemu' type='raw'/>
              <source file='{iso_path}'/>
                            <target dev='hdc' bus='ide'/>
              <readonly/>
            </disk>
            """
            boot_dev = "cdrom"
        elif image_path:
            # Use existing image (Cloud Image scenario)
            # We need to create a COW layer on top of the base image so we don't modify the original
            base_image_name = os.path.basename(image_path)
            disk_filename = f"{name}.qcow2"
            container_disk_path = os.path.join(WORK_DIR, "disks", disk_filename)
            host_disk_path = os.path.join(HOST_WORK_DIR, "disks", disk_filename)
            
            # Create QCOW2 backed by the base image
            # Note: image_path here is the HOST path. We need the CONTAINER path to run qemu-img
            # This is tricky. We'll assume the base image is in /app/images if it was uploaded/downloaded
            # For now, let's just copy it or use backing file if we can resolve path.
            # Simplification: Just copy for now or create new if not exists.
            
            # Better approach: qemu-img create -f qcow2 -b /app/images/base.qcow2 /app/disks/new.qcow2
            # We need to map host_path back to container path.
            container_base_image = image_path.replace(HOST_WORK_DIR, WORK_DIR)

            if not os.path.exists(container_base_image):
                raise FileNotFoundError(
                    f"Base image not found: {container_base_image}. "
                    f"Put it in {os.path.join(WORK_DIR, 'images')} (host: ./images)."
                )

            # Detect backing file format so we don't hardcode qcow2 (Ubuntu cloud images can be qcow2-with-.img or raw)
            try:
                info = subprocess.check_output(["qemu-img", "info", "--output=json", container_base_image], text=True)
                base_format = json.loads(info).get("format") or "qcow2"
            except Exception as e:
                raise RuntimeError(f"Failed to inspect base image with qemu-img: {container_base_image}: {e}")

            subprocess.run(
                ["qemu-img", "create", "-f", "qcow2", "-F", base_format, "-b", container_base_image, container_disk_path],
                check=True,
            )

            # IMPORTANT: libvirt/qemu runs on the HOST (via mounted libvirt socket), so the backing
            # file path embedded inside the qcow2 must be a HOST-visible path, not the container path.
            host_base_image = os.path.join(HOST_WORK_DIR, "images", os.path.basename(container_base_image))
            # Update backing file metadata without checking (-u) since the container cannot access the host path.
            subprocess.run(
                ["qemu-img", "rebase", "-u", "-F", base_format, "-b", host_base_image, container_disk_path],
                check=True,
            )
            
            disk_xml = f"""
            <disk type='file' device='disk'>
              <driver name='qemu' type='qcow2'/>
              <source file='{host_disk_path}'/>
              <target dev='vda' bus='virtio'/>
            </disk>
            """
            
            if cloud_init:
                user_data = f"""#cloud-config
hostname: {name}
manage_etc_hosts: true
users:
  - name: {cloud_init.get('username', 'user')}
    passwd: {cloud_init.get('password', 'password')}
    groups: users, admin
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
ssh_pwauth: true
packages:
{cloud_init.get('packages', '')}
runcmd:
{chr(10).join([f"  - {cmd}" for cmd in cloud_init.get('runcmd', [])])}
  - echo "Cloud-init finished"
"""
                meta_data = f"instance-id: {name}\nlocal-hostname: {name}"
                cidata_iso = self.create_cloud_init_iso(name, user_data, meta_data)
                
                disk_xml += f"""
                <disk type='file' device='cdrom'>
                  <driver name='qemu' type='raw'/>
                  <source file='{cidata_iso}'/>
                  <target dev='sdb' bus='sata'/>
                  <readonly/>
                </disk>
                """

                nets = [str(n) for n in (network_names or [network_name]) if n]
                if not nets:
                        nets = ["default"]

                interfaces_xml = "\n".join(
                        [
                                f"""
                        <interface type='network'>
                            <source network='{n}'/>
                            <model type='virtio'/>
                        </interface>
                        """.rstrip()
                                for n in nets
                        ]
                )

                xml = f"""
        <domain type='kvm'>
          <name>{name}</name>
          <memory unit='KiB'>{memory_mb * 1024}</memory>
          <vcpu placement='static'>{vcpus}</vcpu>
                    <cpu mode='host-passthrough' check='none'/>
                    <os>
                        <type arch='x86_64' machine='{machine_type}'>hvm</type>
            <boot dev='{boot_dev}'/>
            <boot dev='hd'/> 
          </os>
          <features>
            <acpi/>
            <apic/>
          </features>
          <devices>
            <emulator>/usr/bin/qemu-system-x86_64</emulator>
            {disk_xml}
                        {interfaces_xml}
            <graphics type='vnc' port='-1' autoport='yes' listen='0.0.0.0'>
              <listen type='address' address='0.0.0.0'/>
            </graphics>
            <video>
              <model type='virtio' heads='1' primary='yes'/>
            </video>
          </devices>
        </domain>
        """
        try:
            dom = self.conn.defineXML(xml)
            if dom:
                dom.create() # Start the VM
                return {"status": "success", "uuid": dom.UUIDString()}
        except libvirt.libvirtError as e:
            return {"status": "error", "message": str(e)}
        
        return {"status": "error", "message": "Unknown error"}

    def ensure_network(self, name: str, bridge_name: str, gateway_ip: str, dhcp: bool = True, nat: bool = True) -> bool:
        if not self.conn:
            self.connect()

        def _bridge_candidates(base: str, max_attempts: int = 6) -> List[str]:
            """Generate candidate bridge names (<=15 chars) to avoid collisions."""
            base = (base or "br0")[:15]
            cands = [base]
            for i in range(1, max_attempts + 1):
                suffix = str(i)
                trimmed = base[: 15 - len(suffix)] + suffix
                if trimmed not in cands:
                    cands.append(trimmed)
            return cands

        def _define_network(target_bridge: str) -> bool:
            # gateway_ip example: "192.168.100.1"
            try:
                ip = ipaddress.IPv4Address(gateway_ip)
                prefix = str(ip).rsplit('.', 1)[0]
            except Exception:
                prefix = "192.168.100"
                gateway_ip_local = "192.168.100.1"
            else:
                gateway_ip_local = gateway_ip

            dhcp_xml = f"<dhcp><range start=\"{prefix}.50\" end=\"{prefix}.254\"/></dhcp>" if dhcp else ""
            forward_xml = "<forward mode='nat'/>" if nat else ""

            xml = f"""
            <network>
              <name>{name}</name>
              {forward_xml}
              <bridge name='{target_bridge}' stp='on' delay='0'/>
              <ip address='{gateway_ip_local}' netmask='255.255.255.0'>
                {dhcp_xml}
              </ip>
            </network>
            """
            net = self.conn.networkDefineXML(xml)
            if net:
                net.create()
                net.setAutostart(True)
                return True
            return False

        def _reuse_existing() -> bool:
            try:
                net = self.conn.networkLookupByName(name)
                if net is not None:
                    if net.isActive() != 1:
                        net.create()
                    net.setAutostart(True)
                    return True
            except libvirt.libvirtError:
                pass
            return False

        try:
            net = self.conn.networkLookupByName(name)
            if net is not None:
                if net.isActive() != 1:
                    net.create()
                net.setAutostart(True)
                return True
        except libvirt.libvirtError:
            pass

        # If anything goes wrong but the network already exists, just reuse it.
        if _reuse_existing():
            return True

        # Try the requested bridge first; if it is already in use, retry with a suffix.
        last_error = None
        for cand in _bridge_candidates(bridge_name):
            try:
                if _define_network(cand):
                    return True
            except libvirt.libvirtError as e:
                last_error = str(e)
                # Retry on bridge collisions; otherwise bail out.
                if "already exists" in last_error or "already in use by interface" in last_error:
                    if _reuse_existing():
                        return True
                    # If it doesn't exist yet, keep trying different bridges.
                    if "already in use by interface" in last_error:
                        continue
                return False
        # If we exhausted candidates, surface failure.
        if last_error:
            print(f"Failed to create network {name}: {last_error}")
        return False

    def ensure_isolated_network(self, name: str, bridge_name: str) -> bool:
        """Create/ensure a pure L2 libvirt network (no IP/DHCP/NAT).

        Useful when a guest (e.g. OPNsense) should provide routing/DHCP.
        """
        if not self.conn:
            self.connect()

        def _bridge_candidates(base: str, max_attempts: int = 6) -> List[str]:
            base = (base or "br0")[:15]
            cands = [base]
            for i in range(1, max_attempts + 1):
                suffix = str(i)
                trimmed = base[: 15 - len(suffix)] + suffix
                if trimmed not in cands:
                    cands.append(trimmed)
            return cands

        def _define_network(target_bridge: str) -> bool:
            xml = f"""
            <network>
              <name>{name}</name>
              <bridge name='{target_bridge}' stp='on' delay='0'/>
            </network>
            """
            net = self.conn.networkDefineXML(xml)
            if net:
                net.create()
                net.setAutostart(True)
                return True
            return False

        def _reuse_existing() -> bool:
            try:
                net = self.conn.networkLookupByName(name)
                if net is not None:
                    if net.isActive() != 1:
                        net.create()
                    net.setAutostart(True)
                    return True
            except libvirt.libvirtError:
                pass
            return False

        try:
            net = self.conn.networkLookupByName(name)
            if net is not None:
                if net.isActive() != 1:
                    net.create()
                net.setAutostart(True)
                return True
        except libvirt.libvirtError:
            pass

        if _reuse_existing():
            return True

        last_error = None
        for cand in _bridge_candidates(bridge_name):
            try:
                if _define_network(cand):
                    return True
            except libvirt.libvirtError as e:
                last_error = str(e)
                if "already exists" in last_error or "already in use by interface" in last_error:
                    if _reuse_existing():
                        return True
                    if "already in use by interface" in last_error:
                        continue
                return False
        if last_error:
            print(f"Failed to create isolated network {name}: {last_error}")
        return False

    def start_vm(self, name: str):
        if not self.conn:
            self.connect()
        try:
            dom = self.conn.lookupByName(name)
            dom.create()
            return True
        except libvirt.libvirtError:
            return False

    def stop_vm(self, name: str):
        if not self.conn:
            self.connect()
        try:
            dom = self.conn.lookupByName(name)
            dom.destroy() # Force poweroff
            return True
        except libvirt.libvirtError:
            return False

    def delete_vm(self, name: str):
        if not self.conn:
            self.connect()
        try:
            dom = self.conn.lookupByName(name)
            if dom.isActive():
                dom.destroy()
            dom.undefine()
            return True
        except libvirt.libvirtError:
            return False

    def _send_keycodes(self, dom: "libvirt.virDomain", keycodes: List[int], holdtime_ms: int = 30) -> bool:
        """Send raw Linux keycodes to the guest."""
        try:
            dom.sendKey(libvirt.VIR_KEYCODE_SET_LINUX, holdtime_ms, keycodes, 0)
            return True
        except libvirt.libvirtError as e:
            print(f"Failed to send keys to {dom.name()}: {e}")
            return False

    def send_text(self, vm_name: str, text: str, holdtime_ms: int = 30) -> bool:
        """Best-effort type text into the VM's active console.

        Supports lowercase a-z, digits 0-9, space, dash, dot, slash, and newline (Enter).
        """
        if not self.conn:
            self.connect()
        try:
            dom = self.conn.lookupByName(vm_name)
        except libvirt.libvirtError:
            return False

        # Linux input keycodes: include minimal set for installers.
        letters = {
            'a': 30, 'b': 48, 'c': 46, 'd': 32, 'e': 18, 'f': 33, 'g': 34, 'h': 35, 'i': 23,
            'j': 36, 'k': 37, 'l': 38, 'm': 50, 'n': 49, 'o': 24, 'p': 25, 'q': 16, 'r': 19,
            's': 31, 't': 20, 'u': 22, 'v': 47, 'w': 17, 'x': 45, 'y': 21, 'z': 44,
        }
        digits = {'1': 2, '2': 3, '3': 4, '4': 5, '5': 6, '6': 7, '7': 8, '8': 9, '9': 10, '0': 11}
        specials = {' ': 57, '\n': 28, '\r': 28, '-': 12, '.': 52, '/': 53}

        ok = True
        for ch in text:
            if ch in letters:
                ok = self._send_keycodes(dom, [letters[ch]], holdtime_ms) and ok
            elif ch in digits:
                ok = self._send_keycodes(dom, [digits[ch]], holdtime_ms) and ok
            elif ch in specials:
                ok = self._send_keycodes(dom, [specials[ch]], holdtime_ms) and ok
            else:
                # Unsupported character; skip.
                continue

        return ok

# Singleton instance
vm_manager = VMManager()
