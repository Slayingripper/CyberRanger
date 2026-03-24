import React, { useState, useEffect } from 'react';
import { Play, Square, Plus, Monitor, Settings as SettingsIcon, Network, HardDrive, BookOpen } from 'lucide-react';
import axios from 'axios';
import { getApiUrl } from './lib/api';
import Images from './components/Images';
import VNCConsole from './components/VNCConsole';
import NetworkBuilder from './components/NetworkBuilder';
import TopologyViewer from './components/TopologyViewer';
import Settings from './components/Settings';
import Training from './components/Training';
import Modal from './components/Modal';
import { ThemeProvider } from './context/ThemeContext';

const API_URL = getApiUrl();

function AppContent() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [visitedTabs, setVisitedTabs] = useState(new Set(['dashboard']));
  const [vms, setVms] = useState([]);
  const [deployments, setDeployments] = useState({});
  const [loading, setLoading] = useState(false);

  const switchTab = (tab) => {
    setActiveTab(tab);
    setVisitedTabs(prev => {
      if (prev.has(tab)) return prev;
      const next = new Set(prev);
      next.add(tab);
      return next;
    });
    // Let the DOM update (display:none → visible) then nudge ResizeObservers
    // so components like ReactFlow re-measure their containers.
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  };
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [activeConsole, setActiveConsole] = useState(null);
  const [topologyToView, setTopologyToView] = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState({ isOpen: false, vmName: null });

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchData = async () => {
    try {
      const [vmsRes, depsRes] = await Promise.all([
          axios.get(`${API_URL}/vms`),
          axios.get(`${API_URL}/deployments`)
      ]);
      setVms(vmsRes.data);
      setDeployments(depsRes.data);
    } catch (error) {
      console.error("Error fetching data:", error);
    }
  };

  const fetchVMs = fetchData; // Alias for compatibility with existing functions calling fetchVMs

  const handleStartVM = async (name) => {
    await axios.post(`${API_URL}/vms/${name}/start`);
    fetchVMs();
  };

  const handleStopVM = async (name) => {
    await axios.post(`${API_URL}/vms/${name}/stop`);
    fetchVMs();
  };

  const handleDeleteVM = (name) => {
    setDeleteConfirm({ isOpen: true, vmName: name });
  };

  const executeDeleteVM = async () => {
    if (!deleteConfirm.vmName) return;
    await axios.delete(`${API_URL}/vms/${deleteConfirm.vmName}`);
    fetchVMs();
    setDeleteConfirm({ isOpen: false, vmName: null });
  };

  const handleCleanupNetworks = async () => {
    try {
      const res = await axios.post(`${API_URL}/networks/cleanup`);
      await fetchData();
      const count = Number(res.data?.count || 0);
      window.alert(count > 0 ? `Removed ${count} orphaned network${count === 1 ? '' : 's'}.` : 'No orphaned CyberRanger networks found.');
    } catch (error) {
      window.alert(`Failed to clean networks: ${error.response?.data?.detail || error.message}`);
    }
  };

  return (
    <div className="flex h-screen font-sans">
      {/* Sidebar */}
      <div className="w-64 bg-surface border-r border-border flex flex-col">
        <div className="p-6 flex items-center space-x-3 border-b border-border">
          <img src="/cyberranger.jpg" alt="CyberRanger logo" className="h-12 w-12 rounded-lg object-cover border border-border" />
          <span className="text-xl font-bold text-primary">CyberRanger</span>
        </div>
        <nav className="flex-1 p-4 space-y-2">
          <SidebarItem icon={<Monitor />} label="Dashboard" active={activeTab === 'dashboard'} onClick={() => switchTab('dashboard')} />
          <SidebarItem icon={<HardDrive />} label="Images" active={activeTab === 'images'} onClick={() => switchTab('images')} />
          <SidebarItem icon={<Network />} label="Topology Builder" active={activeTab === 'builder'} onClick={() => switchTab('builder')} />
          <SidebarItem icon={<BookOpen />} label="Training" active={activeTab === 'training'} onClick={() => switchTab('training')} />
          <SidebarItem icon={<SettingsIcon />} label="Settings" active={activeTab === 'settings'} onClick={() => switchTab('settings')} />
        </nav>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-auto bg-background">
        <header className="bg-surface border-b border-border p-6">
          <h1 className="text-2xl font-bold capitalize text-primary">{activeTab}</h1>
        </header>
        
        <main className="p-6">
          <div style={{ display: activeTab === 'dashboard' ? undefined : 'none' }}>
            <Dashboard 
              vms={vms} 
              deployments={deployments}
              onStart={handleStartVM} 
              onStop={handleStopVM} 
              onDelete={handleDeleteVM}
              onRefresh={fetchData}
              onCleanupNetworks={handleCleanupNetworks}
              onCreate={() => setShowCreateModal(true)}
              onOpenConsole={(vm) => setActiveConsole({ host: 'localhost', port: vm.vnc_port, name: vm.name })}
              onViewTopology={(topology) => setTopologyToView(topology)}
            />
          </div>
          <div style={{ display: activeTab === 'images' ? undefined : 'none' }}>
            {visitedTabs.has('images') && <Images />}
          </div>
          <div style={{ display: activeTab === 'builder' ? undefined : 'none' }}>
            {visitedTabs.has('builder') && <NetworkBuilder />}
          </div>
          <div style={{ display: activeTab === 'training' ? undefined : 'none' }}>
            {visitedTabs.has('training') && <Training />}
          </div>
          <div style={{ display: activeTab === 'settings' ? undefined : 'none' }}>
            {visitedTabs.has('settings') && <Settings />}
          </div>
        </main>
      </div>

      {topologyToView && (
          <TopologyViewer topology={topologyToView} onClose={() => setTopologyToView(null)} />
      )}

      {showCreateModal && (
        <CreateVMModal onClose={() => setShowCreateModal(false)} onCreated={() => { setShowCreateModal(false); fetchVMs(); }} />
      )}

      {activeConsole && (
        <VNCConsole 
            host={activeConsole.host} 
            port={activeConsole.port} 
            vmName={activeConsole.name} 
            onClose={() => setActiveConsole(null)} 
        />
      )}

      <Modal
        isOpen={deleteConfirm.isOpen}
        onClose={() => setDeleteConfirm({ isOpen: false, vmName: null })}
        title="Delete Virtual Machine"
        footer={
            <>
                <button onClick={() => setDeleteConfirm({ isOpen: false, vmName: null })} className="px-4 py-2 text-secondary hover:text-primary">Cancel</button>
                <button onClick={executeDeleteVM} className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded">Delete</button>
            </>
        }
      >
        <p className="text-secondary">Are you sure you want to delete <span className="font-bold text-primary">{deleteConfirm.vmName}</span>? This action cannot be undone.</p>
      </Modal>
    </div>
  );
}

function App() {
  return (
    <ThemeProvider>
      <AppContent />
    </ThemeProvider>
  );
}

function SidebarItem({ icon, label, active, onClick }) {
  return (
    <button 
      onClick={onClick}
      className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg transition-colors ${
        active 
          ? 'bg-accent text-primary' 
          : 'text-secondary hover:bg-surfaceHover hover:text-primary'
      }`}
    >
      {icon}
      <span className="font-medium">{label}</span>
    </button>
  );
}

function Dashboard({ vms, deployments, onStart, onStop, onDelete, onRefresh, onCleanupNetworks, onCreate, onOpenConsole, onViewTopology }) {
  const groupedVMs = React.useMemo(() => {
    const groups = {};
    const deployedVMNames = new Set();
    const deps = deployments || {}; 

    Object.values(deps).forEach(dep => {
        groups[dep.id] = { ...dep, vmObjects: [] };
        if (dep.vms) dep.vms.forEach(name => deployedVMNames.add(name));
    });

    const other = [];
    vms.forEach(vm => {
        let found = false;
        for (const depId in groups) {
            if (groups[depId].vms && groups[depId].vms.includes(vm.name)) {
                groups[depId].vmObjects.push(vm);
                found = true;
                break;
            }
        }
        if (!found) {
            other.push(vm);
        }
    });
    
    // Sort groups by timestamp descending
    const sortedGroups = Object.values(groups).sort((a, b) => b.timestamp - a.timestamp);
    
    return { groups: sortedGroups, other };
  }, [vms, deployments]);

  const VMCard = ({ vm }) => (
      <div className="bg-surface rounded-xl border border-border p-6 shadow-lg">
        <div className="flex justify-between items-start mb-4">
          <div>
            <h3 className="text-lg font-bold text-primary">{vm.name}</h3>
            <span className={`text-xs px-2 py-1 rounded-full ${
              vm.state === 1 ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'
            }`}>
              {vm.state === 1 ? 'Running' : 'Stopped'}
            </span>
          </div>
          <Monitor className="text-secondary" />
        </div>
        
        <div className="space-y-2 text-sm text-secondary mb-6">
          <div className="flex justify-between">
            <span>Memory:</span>
            <span>{Math.round(vm.memory / 1024)} MB</span>
          </div>
          <div className="flex justify-between">
            <span>vCPUs:</span>
            <span>{vm.vcpus}</span>
          </div>
          <div className="flex justify-between">
            <span>VNC Port:</span>
            <span>{vm.vnc_port || 'N/A'}</span>
          </div>
          {vm.credentials && vm.credentials.username && vm.credentials.password && (
            <div className="border border-blue-800 bg-blue-950/20 rounded p-2">
              <div className="text-xs text-blue-100 font-semibold">Credentials</div>
              <div className="text-xs text-blue-200">User: <code className="bg-background px-1 rounded text-white">{vm.credentials.username}</code></div>
              <div className="text-xs text-blue-200">Pass: <code className="bg-background px-1 rounded text-white">{vm.credentials.password}</code></div>
            </div>
          )}

          </div>

        <div className="flex space-x-2">
          {vm.state !== 1 ? (
            <button onClick={() => onStart(vm.name)} className="flex-1 bg-green-600 hover:bg-green-700 text-primary py-2 rounded flex items-center justify-center space-x-2">
              <Play size={16} /> <span>Start</span>
            </button>
          ) : (
            <button onClick={() => onStop(vm.name)} className="flex-1 bg-yellow-600 hover:bg-yellow-700 text-primary py-2 rounded flex items-center justify-center space-x-2">
              <Square size={16} /> <span>Stop</span>
            </button>
          )}
          <button onClick={() => onDelete(vm.name)} className="px-3 bg-red-900/50 hover:bg-red-900 text-red-200 rounded">
            Delete
          </button>
        </div>

        {vm.state === 1 && vm.vnc_port && (
           <button 
             onClick={() => onOpenConsole(vm)}
             className="mt-3 block w-full text-center bg-accent/30 hover:bg-accent/50 text-accent py-2 rounded border border-accent"
           >
             Open Console (NoVNC)
           </button>
        )}
      </div>
  );

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-semibold text-primary">Active Virtual Machines</h2>
        <div className="flex gap-4">
             <div onClick={onCreate} className="cursor-pointer flex items-center gap-2 bg-accent hover:bg-accentHover text-primary px-4 py-2 rounded text-sm font-medium">
                <Plus size={16} /> Create New VM
             </div>
             <button onClick={onCleanupNetworks} className="bg-red-900/40 hover:bg-red-900/60 text-red-200 px-4 py-2 rounded text-sm">Cleanup Networks</button>
             <button onClick={onRefresh} className="bg-surfaceHover hover:opacity-80 text-primary px-4 py-2 rounded text-sm">Refresh</button>
        </div>
      </div>
      
      {groupedVMs.groups.map(group => (
         <div key={group.id} className="mb-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <div className="flex justify-between items-center mb-4 border-b border-border pb-2">
                 <div className="flex items-center gap-3">
                     <Network className="text-accent" size={24} />
                     <div>
                        <h3 className="text-xl font-bold text-primary">{group.name}</h3>
                        <div className="text-xs text-secondary">ID: {group.id} • {new Date(group.timestamp * 1000).toLocaleString()}</div>
                     </div>
                 </div>
                 {group.topology && (
                     <button onClick={() => onViewTopology(group.topology)} className="text-accent hover:text-accentHover text-sm flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface border border-border hover:bg-surfaceHover transition-all">
                         <Network size={16} /> View Topology
                     </button>
                 )}
            </div>
            {group.vmObjects.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {group.vmObjects.map(vm => (
                        <VMCard key={vm.uuid} vm={vm} />
                    ))}
                </div>
            ) : (
                <div className="text-secondary italic bg-surface/30 p-4 rounded text-center border border-border border-dashed">No active VMs found for this topology (they might be stopped or deleted).</div>
            )}
         </div>
      ))}

      {groupedVMs.other.length > 0 && (
         <div className="mb-8">
             <h3 className="text-lg font-bold text-secondary uppercase tracking-wider mb-4 border-b border-border pb-2 mt-8">Uncategorized VMs</h3>
             <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {groupedVMs.other.map(vm => (
                    <VMCard key={vm.uuid} vm={vm} />
                ))}
             </div>
         </div>
      )}
      
      {(vms.length === 0) && (
          <div className="text-center py-20 bg-surface/20 rounded-xl border border-border border-dashed">
              <div className="text-secondary text-lg">No virtual machines found.</div>
              <div className="text-secondary/60 text-sm mt-2">Deploy a topology or create a VM manually to get started.</div>
          </div>
      )}
    </div>
  );
}

function CreateVMModal({ onClose, onCreated }) {
  const [name, setName] = useState('');
  const [memory, setMemory] = useState(2048);
  const [vcpus, setVcpus] = useState(2);
  const [images, setImages] = useState([]);
  const [selectedImage, setSelectedImage] = useState('');
  const [creating, setCreating] = useState(false);
  const [messageModal, setMessageModal] = useState({ isOpen: false, title: '', message: '', type: 'info' });
  
  // Cloud Init State
  const [enableCloudInit, setEnableCloudInit] = useState(false);
  const [ciUsername, setCiUsername] = useState('user');
  const [ciPassword, setCiPassword] = useState('password');
  const [ciPackages, setCiPackages] = useState('');

  useEffect(() => {
    axios.get(`${API_URL}/images`).then(res => setImages(res.data));
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setCreating(true);
    try {
      const img = images.find(i => i.path === selectedImage);
      
      const payload = {
        name,
        memory_mb: parseInt(memory),
        vcpus: parseInt(vcpus),
        iso_path: img ? img.host_path : null
      };

      if (enableCloudInit) {
        payload.cloud_init = {
          username: ciUsername,
          password: ciPassword,
          packages: ciPackages.split(',').map(p => p.trim()).filter(p => p)
        };
      }

      await axios.post(`${API_URL}/vms`, payload);
      onCreated();
    } catch (e) {
      setMessageModal({ isOpen: true, title: 'Error', message: 'Failed to create VM: ' + (e.response?.data?.detail || e.message), type: 'error' });
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
    <Modal
      isOpen={true}
      onClose={onClose}
      title="Create New VM"
      footer={
        <>
            <button type="button" onClick={onClose} className="px-4 py-2 text-secondary hover:text-primary">Cancel</button>
            <button form="create-vm-form" type="submit" disabled={creating} className="px-4 py-2 bg-accent hover:bg-accentHover text-primary rounded">
              {creating ? 'Creating...' : 'Create VM'}
            </button>
        </>
      }
    >
        <form id="create-vm-form" onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-secondary mb-1">VM Name</label>
            <input type="text" value={name} onChange={e => setName(e.target.value)} className="w-full bg-background border border-border rounded p-2 text-primary" required />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-secondary mb-1">Memory (MB)</label>
              <input type="number" value={memory} onChange={e => setMemory(e.target.value)} className="w-full bg-background border border-border rounded p-2 text-primary" required />
            </div>
            <div>
              <label className="block text-sm text-secondary mb-1">vCPUs</label>
              <input type="number" value={vcpus} onChange={e => setVcpus(e.target.value)} className="w-full bg-background border border-border rounded p-2 text-primary" required />
            </div>
          </div>
          <div>
            <label className="block text-sm text-secondary mb-1">Boot Image (ISO)</label>
            <select value={selectedImage} onChange={e => setSelectedImage(e.target.value)} className="w-full bg-background border border-border rounded p-2 text-primary" required>
              <option value="">Select an image...</option>
              {images.map(img => (
                <option key={img.path} value={img.path}>{img.name}</option>
              ))}
            </select>
          </div>

          {/* Cloud Init Section */}
          <div className="border-t border-border pt-4 mt-4">
            <div className="flex items-center mb-4">
              <input 
                type="checkbox" 
                id="enableCloudInit" 
                checked={enableCloudInit} 
                onChange={e => setEnableCloudInit(e.target.checked)}
                className="w-4 h-4 text-accent bg-background border-border rounded focus:ring-accent ring-offset-surface"
              />
              <label htmlFor="enableCloudInit" className="ml-2 text-sm font-medium text-secondary">Enable Cloud-Init Configuration</label>
            </div>

            {enableCloudInit && (
              <div className="space-y-3 pl-2 border-l-2 border-border">
                <div>
                  <label className="block text-xs text-secondary mb-1">Username</label>
                  <input type="text" value={ciUsername} onChange={e => setCiUsername(e.target.value)} className="w-full bg-background border border-border rounded p-2 text-sm text-primary" />
                </div>
                <div>
                  <label className="block text-xs text-secondary mb-1">Password</label>
                  <input type="password" value={ciPassword} onChange={e => setCiPassword(e.target.value)} className="w-full bg-background border border-border rounded p-2 text-sm text-primary" />
                </div>
                <div>
                  <label className="block text-xs text-secondary mb-1">Packages (comma separated)</label>
                  <textarea 
                    value={ciPackages} 
                    onChange={e => setCiPackages(e.target.value)} 
                    placeholder="git, curl, vim, nmap"
                    className="w-full bg-background border border-border rounded p-2 text-sm h-20 text-primary" 
                  />
                </div>
              </div>
            )}
          </div>
        </form>
    </Modal>

    <Modal
        isOpen={messageModal.isOpen}
        onClose={() => setMessageModal({ ...messageModal, isOpen: false })}
        title={messageModal.title}
        footer={
            <button onClick={() => setMessageModal({ ...messageModal, isOpen: false })} className="px-4 py-2 bg-surface hover:bg-surfaceHover text-primary rounded">Close</button>
        }
    >
        <div className={`text-sm ${messageModal.type === 'error' ? 'text-red-400' : messageModal.type === 'success' ? 'text-green-400' : 'text-secondary'}`}>
            {messageModal.message}
        </div>
    </Modal>
    </>
  );
}

function Scenarios() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div className="bg-surface p-6 rounded-xl border border-border">
        <h3 className="text-xl font-bold mb-2 text-primary">Basic Pentest</h3>
        <p className="text-secondary mb-4">A simple scenario with one attacker machine (Kali) and one victim machine (Metasploitable).</p>
        <button className="bg-accent hover:bg-accentHover text-primary px-4 py-2 rounded">Deploy Scenario</button>
      </div>
      <div className="bg-surface p-6 rounded-xl border border-border">
        <h3 className="text-xl font-bold mb-2 text-primary">Network Forensics</h3>
        <p className="text-secondary mb-4">Analyze traffic between a compromised server and a C2 server.</p>
        <button className="bg-accent hover:bg-accentHover text-primary px-4 py-2 rounded">Deploy Scenario</button>
      </div>
    </div>
  );
}

export default App;
