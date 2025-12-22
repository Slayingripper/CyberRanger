import React, { useState, useEffect } from 'react';
import { Terminal, Play, Square, Plus, Monitor, Settings, Network, HardDrive } from 'lucide-react';
import axios from 'axios';
import Images from './components/Images';
import VNCConsole from './components/VNCConsole';
import NetworkBuilder from './components/NetworkBuilder';

const API_URL = 'http://localhost:8001/api';

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [vms, setVms] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [activeConsole, setActiveConsole] = useState(null);

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

  const handleDeleteVM = async (name) => {
    if(confirm(`Are you sure you want to delete ${name}?`)) {
        await axios.delete(`${API_URL}/vms/${name}`);
        fetchVMs();
    }
  };

  return (
    <div className="flex h-screen bg-gray-900 text-white font-sans">
      {/* Sidebar */}
      <div className="w-64 bg-gray-800 border-r border-gray-700 flex flex-col">
        <div className="p-6 flex items-center space-x-2 border-b border-gray-700">
          <Terminal className="text-blue-400" />
          <span className="text-xl font-bold">CyberRange</span>
        </div>
        <nav className="flex-1 p-4 space-y-2">
          <SidebarItem icon={<Monitor />} label="Dashboard" active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')} />
          <SidebarItem icon={<HardDrive />} label="Images" active={activeTab === 'images'} onClick={() => setActiveTab('images')} />
          <SidebarItem icon={<Network />} label="Topology Builder" active={activeTab === 'builder'} onClick={() => setActiveTab('builder')} />
          <SidebarItem icon={<Settings />} label="Settings" active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} />
        </nav>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-auto">
        <header className="bg-gray-800 border-b border-gray-700 p-6">
          <h1 className="text-2xl font-bold capitalize">{activeTab}</h1>
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
              onOpenConsole={(vm) => setActiveConsole({ host: 'localhost', port: vm.websocket_port, name: vm.name })}
            />
          )}
          {activeTab === 'images' && <Images />}
          {activeTab === 'builder' && <NetworkBuilder />}
          {activeTab === 'settings' && <div className="text-gray-400">Settings placeholder</div>}
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
    </div>
  );
}

function SidebarItem({ icon, label, active, onClick }) {
  return (
    <button 
      onClick={onClick}
      className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg transition-colors ${
        active ? 'bg-blue-600 text-white' : 'text-gray-400 hover:bg-gray-700 hover:text-white'
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function Dashboard({ vms, onStart, onStop, onDelete, onRefresh, onCreate, onOpenConsole }) {
  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-xl font-semibold">Active Virtual Machines</h2>
        <button onClick={onRefresh} className="bg-gray-700 hover:bg-gray-600 px-4 py-2 rounded text-sm">Refresh</button>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {vms.map(vm => (
          <div key={vm.uuid} className="bg-gray-800 rounded-xl border border-gray-700 p-6 shadow-lg">
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="text-lg font-bold">{vm.name}</h3>
                <span className={`text-xs px-2 py-1 rounded-full ${
                  vm.state === 1 ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'
                }`}>
                  {vm.state === 1 ? 'Running' : 'Stopped'}
                </span>
              </div>
              <Monitor className="text-gray-500" />
            </div>
            
            <div className="space-y-2 text-sm text-gray-400 mb-6">
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
                <button onClick={() => onStart(vm.name)} className="flex-1 bg-green-600 hover:bg-green-700 text-white py-2 rounded flex items-center justify-center space-x-2">
                  <Play size={16} /> <span>Start</span>
                </button>
              ) : (
                <button onClick={() => onStop(vm.name)} className="flex-1 bg-yellow-600 hover:bg-yellow-700 text-white py-2 rounded flex items-center justify-center space-x-2">
                  <Square size={16} /> <span>Stop</span>
                </button>
              )}
              <button onClick={() => onDelete(vm.name)} className="px-3 bg-red-900/50 hover:bg-red-900 text-red-200 rounded">
                Delete
              </button>
            </div>
            
            {vm.state === 1 && vm.websocket_port && (
               <button 
                 onClick={() => onOpenConsole(vm)}
                 className="mt-3 block w-full text-center bg-blue-900/30 hover:bg-blue-900/50 text-blue-300 py-2 rounded border border-blue-800"
               >
                 Open Console (NoVNC)
               </button>
            )}
          </div>
        ))}
        
        {/* Add New VM Card */}
        <div onClick={onCreate} className="bg-gray-800/50 rounded-xl border border-gray-700 border-dashed p-6 flex flex-col items-center justify-center text-gray-500 hover:text-gray-300 hover:border-gray-500 cursor-pointer transition-all min-h-[200px]">
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
      alert('Failed to create VM: ' + (e.response?.data?.detail || e.message));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 overflow-y-auto py-10">
      <div className="bg-gray-800 p-6 rounded-xl border border-gray-700 w-full max-w-md my-auto">
        <h2 className="text-xl font-bold mb-4">Create New VM</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">VM Name</label>
            <input type="text" value={name} onChange={e => setName(e.target.value)} className="w-full bg-gray-900 border border-gray-700 rounded p-2" required />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Memory (MB)</label>
              <input type="number" value={memory} onChange={e => setMemory(e.target.value)} className="w-full bg-gray-900 border border-gray-700 rounded p-2" required />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">vCPUs</label>
              <input type="number" value={vcpus} onChange={e => setVcpus(e.target.value)} className="w-full bg-gray-900 border border-gray-700 rounded p-2" required />
            </div>
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Boot Image (ISO)</label>
            <select value={selectedImage} onChange={e => setSelectedImage(e.target.value)} className="w-full bg-gray-900 border border-gray-700 rounded p-2" required>
              <option value="">Select an image...</option>
              {images.map(img => (
                <option key={img.path} value={img.path}>{img.name}</option>
              ))}
            </select>
          </div>

          {/* Cloud Init Section */}
          <div className="border-t border-gray-700 pt-4 mt-4">
            <div className="flex items-center mb-4">
              <input 
                type="checkbox" 
                id="enableCloudInit" 
                checked={enableCloudInit} 
                onChange={e => setEnableCloudInit(e.target.checked)}
                className="w-4 h-4 text-blue-600 bg-gray-700 border-gray-600 rounded focus:ring-blue-600 ring-offset-gray-800"
              />
              <label htmlFor="enableCloudInit" className="ml-2 text-sm font-medium text-gray-300">Enable Cloud-Init Configuration</label>
            </div>

            {enableCloudInit && (
              <div className="space-y-3 pl-2 border-l-2 border-gray-700">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Username</label>
                  <input type="text" value={ciUsername} onChange={e => setCiUsername(e.target.value)} className="w-full bg-gray-900 border border-gray-700 rounded p-2 text-sm" />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Password</label>
                  <input type="password" value={ciPassword} onChange={e => setCiPassword(e.target.value)} className="w-full bg-gray-900 border border-gray-700 rounded p-2 text-sm" />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Packages (comma separated)</label>
                  <textarea 
                    value={ciPackages} 
                    onChange={e => setCiPackages(e.target.value)} 
                    placeholder="git, curl, vim, nmap"
                    className="w-full bg-gray-900 border border-gray-700 rounded p-2 text-sm h-20" 
                  />
                </div>
              </div>
            )}
          </div>

          <div className="flex justify-end space-x-2 mt-6">
            <button type="button" onClick={onClose} className="px-4 py-2 text-gray-400 hover:text-white">Cancel</button>
            <button type="submit" disabled={creating} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded">
              {creating ? 'Creating...' : 'Create VM'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Scenarios() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div className="bg-gray-800 p-6 rounded-xl border border-gray-700">
        <h3 className="text-xl font-bold mb-2">Basic Pentest</h3>
        <p className="text-gray-400 mb-4">A simple scenario with one attacker machine (Kali) and one victim machine (Metasploitable).</p>
        <button className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded">Deploy Scenario</button>
      </div>
      <div className="bg-gray-800 p-6 rounded-xl border border-gray-700">
        <h3 className="text-xl font-bold mb-2">Network Forensics</h3>
        <p className="text-gray-400 mb-4">Analyze traffic between a compromised server and a C2 server.</p>
        <button className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded">Deploy Scenario</button>
      </div>
    </div>
  );
}

export default App;
