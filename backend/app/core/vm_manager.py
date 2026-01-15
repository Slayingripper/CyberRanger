import libvirt
import sys
import os
import subprocess
import json
import ipaddress
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Any
import threading
import time
from app.core.event_bus import event_bus

# Determine working directory
if os.path.exists("/app"):
    WORK_DIR = "/app"
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    WORK_DIR = os.path.join(BASE_DIR, "data")

def _normalize_host_work_dir(host_work_dir: str) -> str:
    """Normalize host working directory used for libvirt file paths.

    A common foot-gun is starting docker compose from a subdirectory like
    `./frontend` which makes `${PWD}` point at that subdirectory.
    In that case, libvirt is given host paths like `<repo>/frontend/disks/...`
    even though the bind mount is `<repo>/disks -> /app/disks`.
    """
    if not host_work_dir:
        return WORK_DIR

    # Container path fallback (shouldn't be passed to libvirt, but keep stable)
    if host_work_dir == WORK_DIR:
        return host_work_dir

    normalized = os.path.normpath(host_work_dir)
    base = os.path.basename(normalized)
    if base in {"frontend", "backend"}:
        parent = os.path.dirname(normalized)
        # If the compose file is in the parent, it's almost certainly the repo root.
        if os.path.isabs(parent):
            return parent
    return normalized


HOST_WORK_DIR = _normalize_host_work_dir(os.environ.get("HOST_WORK_DIR", WORK_DIR))

os.makedirs(os.path.join(WORK_DIR, "images"), exist_ok=True)
os.makedirs(os.path.join(WORK_DIR, "disks"), exist_ok=True)


class VMManager:
    def __init__(self, uri: str = "qemu:///system"):
        self.uri = uri
        self.conn = None
        self.proxies: Dict[str, Dict[str, Any]] = {}
        self.console_threads: Dict[str, Dict[str, Any]] = {}

    def connect(self) -> bool:
        try:
            self.conn = libvirt.open(self.uri)
        except libvirt.libvirtError as e:
            print(f"Failed to open connection to {self.uri}: {e}", file=sys.stderr)
            return False
        return True

    def disconnect(self):
        if self.conn:
            self.conn.close()
        for vm_name, info in self.proxies.items():
            if info.get('proc') and info['proc'].poll() is None:
                info['proc'].terminate()
        self.proxies = {}

    def ensure_vnc_proxy(self, vm_name: str, vnc_port: str) -> Optional[int]:
        if not vnc_port:
            return None
        ws_port = int(vnc_port) + 1000
        if vm_name in self.proxies:
            proc_info = self.proxies[vm_name]
            if proc_info['proc'].poll() is None:
                if proc_info['vnc_port'] == vnc_port:
                    return ws_port
                else:
                    proc_info['proc'].terminate()
        try:
            cmd = [sys.executable, "-m", "websockify", f"0.0.0.0:{ws_port}", f"127.0.0.1:{vnc_port}"]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.proxies[vm_name] = {'proc': proc, 'port': ws_port, 'vnc_port': vnc_port}
            return ws_port
        except Exception as e:
            print(f"Failed to start websockify: {e}")
            return None

    def list_domains(self) -> List[Dict[str, Any]]:
        if not self.conn:
            self.connect()
        if not self.conn:
            return []
        domains: List[Dict[str, Any]] = []
        try:
            for domain_id in self.conn.listDomainsID():
                dom = self.conn.lookupByID(domain_id)
                domains.append(self._get_domain_info(dom))
            for name in self.conn.listDefinedDomains():
                dom = self.conn.lookupByName(name)
                domains.append(self._get_domain_info(dom))
        except libvirt.libvirtError:
            pass
        return domains

    def list_domains_with_interfaces(self) -> List[Dict[str, Any]]:
        if not self.conn:
            self.connect()
        if not self.conn:
            return []
        results: List[Dict[str, Any]] = []
        try:
            domain_names: List[str] = []
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
                iface_info: List[Dict[str, Any]] = []
                try:
                    addrs = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE, 0)
                except libvirt.libvirtError:
                    addrs = {}
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
                    addrs_list: List[str] = []
                    for a in data.get("addrs", []) or []:
                        ip = a.get("addr")
                        if ip:
                            addrs_list.append(ip)
                    iface_info.append({
                        "name": ifname,
                        "mac": mac,
                        "network": mac_to_net.get(mac.lower()) if mac else None,
                        "ips": addrs_list,
                    })
                results.append({"name": name, "interfaces": iface_info})
        except libvirt.libvirtError:
            pass
        return results

    def _get_domain_info(self, dom):
        state, maxmem, mem, cpus, cput = dom.info()
        try:
            xml_desc = dom.XMLDesc(0)
            root = ET.fromstring(xml_desc)
            graphics = root.find("./devices/graphics")
            vnc_port = None
            if graphics is not None and graphics.get('type') == 'vnc':
                vnc_port = graphics.get('port')
        except Exception:
            vnc_port = None
        websocket_port = None
        # VNC Proxy is now handled by FastAPI directly
        # if state == 1 and vnc_port and vnc_port != '-1':
        #     websocket_port = self.ensure_vnc_proxy(dom.name(), vnc_port)
        return {
            "id": dom.ID(),
            "name": dom.name(),
            "uuid": dom.UUIDString(),
            "state": state,
            "memory": mem,
            "vcpus": cpus,
            "vnc_port": vnc_port,
            "websocket_port": websocket_port,
        }

    def create_cloud_init_iso(self, vm_name: str, user_data: str, meta_data: str) -> str:
        config_dir = os.path.join(WORK_DIR, "disks", f"{vm_name}_cidata")
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "user-data"), "w") as f:
            f.write(user_data)
        with open(os.path.join(config_dir, "meta-data"), "w") as f:
            f.write(meta_data)
        iso_path = os.path.join(WORK_DIR, "disks", f"{vm_name}_cidata.iso")
        host_iso_path = os.path.join(HOST_WORK_DIR, "disks", f"{vm_name}_cidata.iso")
        cmd = [
            "genisoimage",
            "-output", iso_path,
            "-volid", "cidata",
            "-joliet",
            "-rock",
            config_dir,
        ]
        subprocess.run(cmd, check=True)
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
    ) -> Dict[str, Any]:
        if not self.conn:
            self.connect()
        if not self.conn:
            return {"status": "error", "message": "No libvirt connection"}

        try:
            existing = self.conn.lookupByName(name)
            if existing is not None:
                if existing.isActive():
                    existing.destroy()
                existing.undefineFlags(0)
        except libvirt.libvirtError:
            pass

        disk_xml = ""
        boot_dev = "hd"
        machine_type = "pc-q35-6.2"

        if iso_path:
            machine_type = "pc-i440fx-6.2"
            disk_filename = f"{name}.qcow2"
            container_disk_path = os.path.join(WORK_DIR, "disks", disk_filename)
            host_disk_path = os.path.join(HOST_WORK_DIR, "disks", disk_filename)
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
            disk_filename = f"{name}.qcow2"
            container_disk_path = os.path.join(WORK_DIR, "disks", disk_filename)
            host_disk_path = os.path.join(HOST_WORK_DIR, "disks", disk_filename)
            container_base_image = image_path.replace(HOST_WORK_DIR, WORK_DIR)
            if not os.path.exists(container_base_image):
                raise FileNotFoundError(
                    f"Base image not found: {container_base_image}. Place it under {os.path.join(WORK_DIR, 'images')}"
                )
            try:
                info = subprocess.check_output(["qemu-img", "info", "--output=json", container_base_image], text=True)
                base_format = json.loads(info).get("format") or "qcow2"
            except Exception as e:
                raise RuntimeError(f"Failed to inspect base image with qemu-img: {container_base_image}: {e}")
            subprocess.run(
                ["qemu-img", "create", "-f", "qcow2", "-F", base_format, "-b", container_base_image, container_disk_path],
                check=True,
            )
            host_base_image = os.path.join(HOST_WORK_DIR, "images", os.path.basename(container_base_image))
            subprocess.run(["qemu-img", "rebase", "-u", "-F", base_format, "-b", host_base_image, container_disk_path], check=True)
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
        interfaces_xml = "\n".join([
            f"""
            <interface type='network'>
              <source network='{n}'/>
              <model type='virtio'/>
            </interface>
            """.rstrip()
            for n in nets
        ])

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
                dom.create()
                # Try to start console streaming in background if possible
                try:
                    # No definition context here; caller may start stream by calling start_console_stream
                    pass
                except Exception:
                    pass
                return {"status": "success", "uuid": dom.UUIDString()}
        except libvirt.libvirtError as e:
            return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Unknown error"}

    def start_console_stream(self, vm_name: str, definition_id: str, level_idx: int):
        """Start background thread that reads the domain's console and publishes events via event_bus."""
        if vm_name in self.console_threads:
            return

        try:
            if not self.conn:
                self.connect()
            dom = self.conn.lookupByName(vm_name)
            stream = self.conn.newStream(0)
            try:
                dom.openConsole(None, stream, 0)
            except libvirt.libvirtError:
                # No console available
                try:
                    stream.finish()
                except Exception:
                    pass
                return

            stop_event = threading.Event()

            def _reader():
                try:
                    while not stop_event.is_set():
                        try:
                            data = stream.recv(4096)
                            if not data:
                                time.sleep(0.1)
                                continue
                            try:
                                txt = data.decode('utf-8', errors='replace')
                            except Exception:
                                txt = repr(data)
                            # publish to any runs matching this definition and level
                            asyncio_loop = None
                            try:
                                import asyncio
                                asyncio_loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(asyncio_loop)
                                asyncio_loop.run_until_complete(event_bus.publish_by_definition_level(definition_id, level_idx, {"type": "console", "vm": vm_name, "msg": txt, "ts": time.time()}))
                            finally:
                                if asyncio_loop:
                                    try:
                                        asyncio_loop.close()
                                    except Exception:
                                        pass
                        except libvirt.libvirtError:
                            break
                        except Exception:
                            time.sleep(0.1)
                finally:
                    try:
                        stream.finish()
                    except Exception:
                        pass

            t = threading.Thread(target=_reader, name=f"console-{vm_name}", daemon=True)
            self.console_threads[vm_name] = {"thread": t, "stop": stop_event}
            t.start()
        except Exception:
            return

    def stop_console_stream(self, vm_name: str):
        info = self.console_threads.get(vm_name)
        if not info:
            return
        try:
            info['stop'].set()
            info['thread'].join(timeout=1.0)
        except Exception:
            pass
        try:
            del self.console_threads[vm_name]
        except Exception:
            pass

    def ensure_network(self, name: str, bridge_name: str, gateway_ip: str, dhcp: bool = True, nat: bool = True) -> bool:
        if not self.conn:
            self.connect()
        if not self.conn:
            return False
        conn = self.conn

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
            try:
                ip_obj = ipaddress.IPv4Address(gateway_ip)
                prefix = str(ip_obj).rsplit('.', 1)[0]
                gw_local = gateway_ip
            except Exception:
                prefix = "192.168.100"
                gw_local = "192.168.100.1"
            dhcp_xml = f"<dhcp><range start=\"{prefix}.50\" end=\"{prefix}.254\"/></dhcp>" if dhcp else ""
            forward_xml = "<forward mode='nat'/>" if nat else ""
            xml = f"""
            <network>
              <name>{name}</name>
              {forward_xml}
              <bridge name='{target_bridge}' stp='on' delay='0'/>
              <ip address='{gw_local}' netmask='255.255.255.0'>
                {dhcp_xml}
              </ip>
            </network>
            """
            net = conn.networkDefineXML(xml)
            if net:
                net.create()
                net.setAutostart(True)
                return True
            return False

        def _reuse_existing() -> bool:
            try:
                net = conn.networkLookupByName(name)
                if net is not None:
                    if net.isActive() != 1:
                        net.create()
                    net.setAutostart(True)
                    return True
            except libvirt.libvirtError:
                pass
            return False

        try:
            net = conn.networkLookupByName(name)
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
            print(f"Failed to create network {name}: {last_error}")
        return False

    def ensure_isolated_network(self, name: str, bridge_name: str) -> bool:
        if not self.conn:
            self.connect()
        if not self.conn:
            return False
        conn = self.conn

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
            net = conn.networkDefineXML(xml)
            if net:
                net.create()
                net.setAutostart(True)
                return True
            return False

        def _reuse_existing() -> bool:
            try:
                net = conn.networkLookupByName(name)
                if net is not None:
                    if net.isActive() != 1:
                        net.create()
                    net.setAutostart(True)
                    return True
            except libvirt.libvirtError:
                pass
            return False

        try:
            net = conn.networkLookupByName(name)
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

    def start_vm(self, name: str) -> bool:
        if not self.conn:
            self.connect()
        if not self.conn:
            return False
        try:
            dom = self.conn.lookupByName(name)
            if dom and dom.isActive() != 1:
                dom.create()
            return True
        except libvirt.libvirtError:
            return False

    def stop_vm(self, name: str) -> bool:
        if not self.conn:
            self.connect()
        if not self.conn:
            return False
        try:
            dom = self.conn.lookupByName(name)
            if dom and dom.isActive() == 1:
                dom.destroy()
            return True
        except libvirt.libvirtError:
            return False

    def delete_vm(self, name: str) -> bool:
        if not self.conn:
            self.connect()
        if not self.conn:
            return False
        try:
            dom = self.conn.lookupByName(name)
            if dom:
                if dom.isActive() == 1:
                    dom.destroy()
                dom.undefineFlags(0)
            return True
        except libvirt.libvirtError:
            return False

    def _send_keycodes(self, dom: "libvirt.virDomain", keycodes: List[int], holdtime_ms: int = 30) -> bool:
        try:
            dom.sendKey(libvirt.VIR_KEYCODE_SET_LINUX, holdtime_ms, keycodes, 0)
            return True
        except libvirt.libvirtError as e:
            print(f"Failed to send keys to {dom.name()}: {e}")
            return False

    def send_text(self, vm_name: str, text: str, holdtime_ms: int = 30) -> bool:
        if not self.conn:
            self.connect()
        if not self.conn:
            return False
        try:
            dom = self.conn.lookupByName(vm_name)
        except libvirt.libvirtError:
            return False
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
                continue
        return ok


vm_manager = VMManager()
