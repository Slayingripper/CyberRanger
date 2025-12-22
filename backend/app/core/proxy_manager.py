import subprocess
import time
import socket

class ProxyManager:
    def __init__(self):
        self.proxies = {} # vm_name -> process

    def start_proxy(self, vm_name: str, vnc_port: int, listen_port: int):
        if vm_name in self.proxies:
            # Check if still running
            if self.proxies[vm_name].poll() is None:
                return True # Already running
            
        # Start websockify
        # websockify --web /opt/novnc 6080 localhost:5900
        cmd = [
            "websockify",
            "--web", "/opt/novnc",
            str(listen_port),
            f"localhost:{vnc_port}"
        ]
        
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.proxies[vm_name] = proc
            return True
        except Exception as e:
            print(f"Failed to start proxy: {e}")
            return False

    def stop_proxy(self, vm_name: str):
        if vm_name in self.proxies:
            proc = self.proxies[vm_name]
            proc.terminate()
            del self.proxies[vm_name]

proxy_manager = ProxyManager()
