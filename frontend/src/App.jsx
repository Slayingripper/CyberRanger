import React, { useState, useEffect } from 'react';
import { Terminal, Play, Square, Plus, Monitor, Settings as SettingsIcon, Network, HardDrive, BookOpen } from 'lucide-react';
import axios from 'axios';
import { getApiUrl } from './lib/api';
import Images from './components/Images';
import VNCConsole from './components/VNCConsole';
import NetworkBuilder from './components/NetworkBuilder';
import Settings from './components/Settings';
import Training from './components/Training';
import Modal from './components/Modal';
import { ThemeProvider } from './context/ThemeContext';

const API_URL = getApiUrl();

function AppContent() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [vms, setVms] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [activeConsole, setActiveConsole] = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState({ isOpen: false, vmName: null });

  useEffect(() => {
    fetchVMs();
  }, []);

  const fetchVMs = async () => {
    try {
      const response = await axios.get(`${API_URL}/vms`);
      setVms(response.data);
    } catch (error) {
      console.error("Error fetching VMs:", error);
    }
  };

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

  return (
    <div className="flex h-screen font-sans">
      {/* Sidebar */}
      <div className="w-64 bg-surface border-r border-border flex flex-col">
        <div className="p-6 flex items-center space-x-2 border-b border-border">
          <Terminal className="text-accent" />
          <span className="text-xl font-bold text-primary">CyberRange</span>
        </div>
        <nav className="flex-1 p-4 space-y-2">
          <SidebarItem icon={<Monitor />} label="Dashboard" active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')} />
          <SidebarItem icon={<HardDrive />} label="Images" active={activeTab === 'images'} onClick={() => setActiveTab('images')} />
          <SidebarItem icon={<Network />} label="Topology Builder" active={activeTab === 'builder'} onClick={() => setActiveTab('builder')} />
          <SidebarItem icon={<BookOpen />} label="Training" active={activeTab === 'training'} onClick={() => setActiveTab('training')} />
          <SidebarItem icon={<SettingsIcon />} label="Settings" active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} />
        </nav>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-auto bg-background">
        <header className="bg-surface border-b border-border p-6">
          <h1 className="text-2xl font-bold capitalize text-primary">{activeTab}</h1>
        </header>
        
        <main className="p-6">
          {activeTab === 'dashboard' && (
            <Dashboard 
              vms={vms} 
              onStart={handleStartVM} 
              onStop={handleStopVM} 
              onDelete={handleDeleteVM}
              onRefresh={fetchVMs}
              onCreate={() => setShowCreateModal(true)}
              onOpenConsole={(vm) => setActiveConsole({ host: 'localhost', port: vm.vnc_port, name: vm.name })}
            />
          )}
          {activeTab === 'images' && <Images />}
          {activeTab === 'builder' && <NetworkBuilder />}
          {activeTab === 'training' && <Training />}
          {activeTab === 'settings' && <Settings />}
        </main>
      </div>

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

function Dashboard({ vms, onStart, onStop, onDelete, onRefresh, onCreate, onOpenConsole }) {
  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-semibold text-primary">Active Virtual Machines</h2>
        <button onClick={onRefresh} className="bg-surfaceHover hover:opacity-80 text-primary px-4 py-2 rounded text-sm">Refresh</button>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {vms.map(vm => (
          <div key={vm.uuid} className="bg-surface rounded-xl border border-border p-6 shadow-lg">
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
        ))}
        
        {/* Add New VM Card */}
        <div onClick={onCreate} className="bg-surface/50 rounded-xl border border-border border-dashed p-6 flex flex-col items-center justify-center text-secondary hover:text-primary hover:border-secondary cursor-pointer transition-all min-h-[200px]">
          <Plus size={48} className="mb-2" />
          <span className="font-medium">Create New VM</span>
        </div>
      </div>
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
