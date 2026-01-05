import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import ReactFlow, {
  ReactFlowProvider,
  addEdge,
  useNodesState,
  useEdgesState,
  Controls,
  Background,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Play, Plus, Trash2, Upload, FileText, Target, Shield, Flag } from 'lucide-react';
import yaml from 'js-yaml';
import axios from 'axios';
import CustomNode from './CustomNode';
import Modal from './Modal';

const initialNodes = [
  {
    id: '1',
    type: 'custom',
    data: { label: 'Internet Gateway', image: 'gateway', cpu: 1, ram: 512, assets: [] },
    position: { x: 250, y: 5 },
  },
];

const PREDEFINED_TOPOLOGIES = {
    "simple-client-server": {
        scenario: {
            name: 'Simple Client-Server',
            team: 'blue',
            objective: 'Deploy a simple web server and client.',
            difficulty: 'easy'
        },
        nodes: [
            { id: '1', type: 'custom', position: { x: 100, y: 100 }, data: { label: 'Web Server', image: 'ubuntu-20.04', cpu: 2, ram: 2048, assets: [{ type: 'package', value: 'nginx' }] } },
            { id: '2', type: 'custom', position: { x: 400, y: 100 }, data: { label: 'Client', image: 'ubuntu-20.04', cpu: 1, ram: 1024, assets: [{ type: 'package', value: 'curl' }] } }
        ],
        edges: [
            { id: 'e1-2', source: '1', target: '2' }
        ]
    },
    "iso-install-lab": {
        scenario: {
            name: 'ISO Install Lab',
            team: 'blue',
            objective: 'Boot Linux installers from ISO and install manually.',
            difficulty: 'easy'
        },
        nodes: [
            { id: '1', type: 'custom', position: { x: 120, y: 120 }, data: { label: 'Installer VM 1 (Xubuntu ISO)', image: 'xubuntu-24.04.3-minimal-amd64.iso', cpu: 2, ram: 2048, assets: [] } },
            { id: '2', type: 'custom', position: { x: 460, y: 120 }, data: { label: 'Installer VM 2 (Xubuntu ISO)', image: 'xubuntu-24.04.3-minimal-amd64.iso', cpu: 2, ram: 2048, assets: [] } }
        ],
        edges: [
            { id: 'e1-2', source: '1', target: '2' }
        ]
    },
    "sl1-2-smart-home-pv": {
        scenario: {
            name: 'Smart Home PV (SL1-2)',
            team: 'red',
            objective: 'Deploy the Smart Home PV challenge services on a single game-server VM.',
            difficulty: 'hard',
            sources: {
                // Auto-download Ubuntu base image if missing
                'ubuntu-20.04': 'https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img'
            }
        },
        nodes: [
            {
                id: '1',
                type: 'custom',
                position: { x: 240, y: 140 },
                data: {
                    label: 'game-server (Ubuntu)',
                    image: 'ubuntu-20.04',
                    cpu: 4,
                    ram: 8192,
                    assets: [
                        { type: 'package', value: 'git' },
                        { type: 'package', value: 'docker.io' },
                        { type: 'package', value: 'docker-compose' },
                        { type: 'command', value: 'systemctl enable --now docker' },
                        { type: 'command', value: 'cd /opt && (test -d sl1-2 || git clone --depth 1 https://github.com/Slayingripper/SL1-2.git sl1-2)' },
                        { type: 'command', value: 'docker network inspect playground-net >/dev/null 2>&1 || docker network create --subnet 172.20.0.0/24 playground-net' },
                        { type: 'command', value: 'cd /opt/sl1-2/provisioning/files/smart-home-pv && (docker compose up -d --build || docker-compose up -d --build)' }
                    ]
                }
            }
        ],
        edges: []
    },
    "sl1-2-smart-home-pv-3vm": {
        scenario: {
            name: 'Smart Home PV (SL1-2) - 3 VMs',
            team: 'red',
            objective: 'Kali attacker VM + game-server VM + OPNsense blue-team gateway.',
            difficulty: 'hard',
            sources: {
                // Auto-download Ubuntu base image if missing
                'ubuntu-20.04': 'https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img',

                // Kali QEMU image is distributed as a .7z; backend will download + extract to qcow2.
                'kali-linux': {
                    url: 'https://cdimage.kali.org/current/kali-linux-2025.4-qemu-amd64.7z',
                    filename: 'kali-linux-2025.4-qemu-amd64.7z',
                    extract: {
                        type: '7z',
                        output_filename: 'kali-linux-2025.4-qemu-amd64.qcow2',
                        member_glob: '*.qcow2'
                    }
                },

                // OPNsense (downloaded once, cached as opnsense.img)
                'opnsense': {
                    url: 'https://pkg.opnsense.org/releases/25.7/OPNsense-25.7-vga-amd64.img.bz2',
                    filename: 'OPNsense-25.7-vga-amd64.img.bz2',
                    extract: {
                        type: 'bz2',
                        output_filename: 'opnsense.img'
                    },
                    min_bytes: 200000000
                }
            }
        },
        nodes: [
            {
                id: 'attacker',
                type: 'custom',
                position: { x: 80, y: 140 },
                data: {
                    label: 'Attacker (Kali VM)',
                    image: 'kali-linux',
                    cpu: 2,
                    ram: 4096,
                    assets: []
                }
            },
            {
                id: 'game',
                type: 'custom',
                position: { x: 360, y: 140 },
                data: {
                    label: 'game-server (Ubuntu)',
                    image: 'ubuntu-20.04',
                    cpu: 4,
                    ram: 8192,
                    assets: [
                        { type: 'package', value: 'git' },
                        { type: 'package', value: 'docker.io' },
                        { type: 'package', value: 'docker-compose' },
                        { type: 'command', value: 'systemctl enable --now docker' },
                        { type: 'command', value: 'mkdir -p /opt && chown user:user /opt' },
                        { type: 'command', value: 'cd /opt && (test -d sl1-2 || git clone --depth 1 https://github.com/Slayingripper/SL1-2.git sl1-2)' },
                        { type: 'command', value: 'docker network inspect playground-net >/dev/null 2>&1 || docker network create --subnet 172.20.0.0/24 playground-net' },
                        { type: 'command', value: 'cd /opt/sl1-2/provisioning/files/smart-home-pv && (docker compose up -d --build || docker-compose up -d --build)' }
                    ]
                }
            },
            {
                id: 'gateway',
                type: 'custom',
                position: { x: 640, y: 140 },
                data: {
                    label: 'Blue Team Gateway (OPNsense)',
                    image: 'opnsense',
                    cpu: 2,
                    ram: 4096,
                    assets: []
                }
            }
        ],
        edges: [
            { id: 'e-gateway-attacker', source: 'gateway', target: 'attacker' },
            { id: 'e-gateway-game', source: 'gateway', target: 'game' }
        ]
    },
    "attacker-victim": {
        scenario: {
            name: 'Attacker vs Victim (Linux)',
            team: 'red',
            objective: 'Deploy a basic attacker and victim pair (Linux).',
            difficulty: 'easy'
        },
        nodes: [
            { id: '1', type: 'custom', position: { x: 100, y: 100 }, data: { label: 'Attacker (Kali)', image: 'kali-linux', cpu: 2, ram: 4096, assets: [{ type: 'package', value: 'nmap' }] } },
            { id: '2', type: 'custom', position: { x: 400, y: 100 }, data: { label: 'Victim (Ubuntu)', image: 'ubuntu-20.04', cpu: 2, ram: 2048, assets: [{ type: 'package', value: 'openssh-server' }] } }
        ],
        edges: [
            { id: 'e1-2', source: '1', target: '2' }
        ]
    }
};
let id = 0;
const getId = () => `dndnode_${id++}`;

const API_URL = 'http://localhost:8001/api';

const SCENARIO_DEFAULTS = {
    name: 'New Scenario',
    team: 'blue',
    objective: 'Defend the network against incoming attacks.',
    difficulty: 'easy',
    network_prefix: ''
};

const NetworkBuilder = () => {
  const reactFlowWrapper = useRef(null);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [reactFlowInstance, setReactFlowInstance] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [availableImages, setAvailableImages] = useState([]);
    const [runtimeVms, setRuntimeVms] = useState([]);
    const [viewportRestored, setViewportRestored] = useState(false);
  
  // Scenario State
  const [scenarioConfig, setScenarioConfig] = useState({
      ...SCENARIO_DEFAULTS
  });
  const [showScenarioSettings, setShowScenarioSettings] = useState(false);
  const [isDeploying, setIsDeploying] = useState(false);
    const [deployJobId, setDeployJobId] = useState(null);
    const [deployJob, setDeployJob] = useState(null);
    const [deployJobError, setDeployJobError] = useState(null);
    const [messageModal, setMessageModal] = useState({ isOpen: false, title: '', message: '', type: 'info' });

  const nodeTypes = useMemo(() => ({ custom: CustomNode }), []);

  const formatBytes = (bytes) => {
      const b = Number(bytes || 0);
      if (!Number.isFinite(b) || b <= 0) return '0 B';
      const units = ['B', 'KB', 'MB', 'GB', 'TB'];
      const idx = Math.min(units.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
      const val = b / Math.pow(1024, idx);
      const digits = idx === 0 ? 0 : (val < 10 ? 2 : 1);
      return `${val.toFixed(digits)} ${units[idx]}`;
  };

  const formatSpeed = (bps) => {
      const v = Number(bps || 0);
      if (!Number.isFinite(v) || v <= 0) return null;
      return `${formatBytes(v)}/s`;
  };

  const formatEta = (seconds) => {
      const s = Number(seconds);
      if (!Number.isFinite(s) || s <= 0) return null;
      if (s < 60) return `${Math.round(s)}s`;
      if (s < 3600) return `${Math.round(s / 60)}m`;
      return `${(s / 3600).toFixed(1)}h`;
  };

  const vmInfoForNode = (nodeId) => {
      const suffix = `_${nodeId}`;
      return runtimeVms.find(v => v?.name?.endsWith(suffix)) || null;
  };

  const primaryIp = (vmInfo) => {
      if (!vmInfo || !vmInfo.interfaces) return null;
      for (const iface of vmInfo.interfaces) {
          if (iface?.ips && iface.ips.length > 0) {
              return iface.ips[0];
          }
      }
      return null;
  };

  // Persistence Logic - Load saved topology on mount
  useEffect(() => {
      const saved = localStorage.getItem('networkTopology');
      if (saved) {
          try {
              const { nodes: savedNodes, edges: savedEdges, scenario: savedScenario } = JSON.parse(saved);
              if (Array.isArray(savedNodes)) setNodes(savedNodes);
              if (Array.isArray(savedEdges)) setEdges(savedEdges);
              if (savedScenario) setScenarioConfig(savedScenario);
          } catch (err) {
              console.error('Failed to load saved topology', err);
          }
      }
  }, []);

  // Restore viewport when ReactFlow instance is ready
  useEffect(() => {
      if (reactFlowInstance && !viewportRestored) {
          const saved = localStorage.getItem('networkTopology');
          if (saved) {
              try {
                  const { viewport } = JSON.parse(saved);
                  if (viewport) {
                      // Small delay to ensure ReactFlow is fully initialized
                      setTimeout(() => {
                          reactFlowInstance.setViewport(viewport);
                          setViewportRestored(true);
                      }, 100);
                  } else {
                      // No saved viewport, fit the view to show all nodes
                      setTimeout(() => {
                          reactFlowInstance.fitView();
                          setViewportRestored(true);
                      }, 100);
                  }
              } catch (err) {
                  console.error('Failed to restore viewport', err);
                  setViewportRestored(true);
              }
          } else {
              // No saved topology, fit the view
              setTimeout(() => {
                  reactFlowInstance.fitView();
                  setViewportRestored(true);
              }, 100);
          }
      }
  }, [reactFlowInstance, viewportRestored]);

  // Save topology when it changes
  useEffect(() => {
      const saveTopology = () => {
          if (nodes.length > 0 || edges.length > 0) {
              const viewport = reactFlowInstance ? reactFlowInstance.getViewport() : null;
              const topology = { nodes, edges, scenario: scenarioConfig, viewport };
              localStorage.setItem('networkTopology', JSON.stringify(topology));
          }
      };
      saveTopology();
  }, [nodes, edges, scenarioConfig, reactFlowInstance]);

  // Save viewport on page unload/visibility change
  useEffect(() => {
      const saveViewport = () => {
          if (reactFlowInstance) {
              const saved = localStorage.getItem('networkTopology');
              if (saved) {
                  try {
                      const topology = JSON.parse(saved);
                      topology.viewport = reactFlowInstance.getViewport();
                      localStorage.setItem('networkTopology', JSON.stringify(topology));
                  } catch (err) {
                      console.error('Failed to save viewport', err);
                  }
              }
          }
      };

      window.addEventListener('beforeunload', saveViewport);
      window.addEventListener('visibilitychange', saveViewport);
      document.addEventListener('visibilitychange', saveViewport);

      return () => {
          window.removeEventListener('beforeunload', saveViewport);
          window.removeEventListener('visibilitychange', saveViewport);
          document.removeEventListener('visibilitychange', saveViewport);
          saveViewport();
      };
  }, [reactFlowInstance]);

  useEffect(() => {
      const fetchImages = () => {
          axios.get(`${API_URL}/images`)
              .then(res => setAvailableImages(res.data))
              .catch(err => console.error("Failed to fetch images", err));
      };
      fetchImages();
      const timer = setInterval(fetchImages, 10000); // Refresh every 10 seconds
      return () => clearInterval(timer);
  }, []);

  useEffect(() => {
      let timer;
      const fetchRuntime = async () => {
          try {
              const res = await axios.get(`${API_URL}/runtime/vms`);
              setRuntimeVms(res.data || []);
          } catch (err) {
              console.error('Failed to fetch runtime VMs', err);
          }
      };
      fetchRuntime();
      timer = setInterval(fetchRuntime, 5000);
      return () => clearInterval(timer);
  }, []);

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge(params, eds)),
    [],
  );

  const handleFileUpload = (event) => {
      const file = event.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (e) => {
          try {
              const content = e.target.result;
              const parsed = yaml.load(content);
              
              if (parsed.nodes) {
                  // Map YAML nodes to ReactFlow nodes
                  const newNodes = parsed.nodes.map(n => ({
                      id: n.id,
                      type: 'custom',
                      position: n.position || { x: 100, y: 100 },
                      data: {
                          label: n.label || 'VM',
                          image: n.config?.image || 'ubuntu-20.04',
                          cpu: n.config?.cpu || 1,
                          ram: n.config?.ram || 1024,
                          assets: n.config?.assets || [],
                          automation: n.config?.automation || null
                      }
                  }));
                  setNodes(newNodes);
              }

              if (parsed.scenario) {
                  setScenarioConfig({ ...SCENARIO_DEFAULTS, ...(parsed.scenario || {}) });
              }
              
              if (parsed.edges) {
                  const newEdges = parsed.edges.map((e, idx) => ({
                      id: e.id || `e${idx}`,
                      source: e.source,
                      target: e.target
                  }));
                  setEdges(newEdges);
              }
              
              setMessageModal({ isOpen: true, title: 'Success', message: 'Topology loaded successfully!', type: 'success' });
          } catch (err) {
              console.error(err);
              setMessageModal({ isOpen: true, title: 'Error', message: "Failed to parse YAML file: " + err.message, type: 'error' });
          }
      };
      reader.readAsText(file);
  };

  const loadPreset = (presetName) => {
      const preset = PREDEFINED_TOPOLOGIES[presetName];
      if (preset) {
          setNodes(preset.nodes);
          setEdges(preset.edges);
          if (preset.scenario) setScenarioConfig({ ...SCENARIO_DEFAULTS, ...(preset.scenario || {}) });
      }
  };

  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event) => {
      event.preventDefault();

      const type = event.dataTransfer.getData('application/reactflow');

      // check if the dropped element is valid
      if (typeof type === 'undefined' || !type) {
        return;
      }

      const position = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      
      const image = event.dataTransfer.getData('image');
      const isRouter = type === 'router';

      const newNode = {
        id: getId(),
        type: 'custom', 
        position,
        data: { 
            label: isRouter ? 'Router' : (image || 'New VM'), 
            image: isRouter ? 'gateway' : (image || 'ubuntu-20.04'), 
            cpu: isRouter ? 1 : 2, 
            ram: isRouter ? 512 : 2048, 
            assets: [] 
        },
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [reactFlowInstance],
  );

  const onNodeClick = (event, node) => {
    setSelectedNode(node);
  };

  const updateNodeData = (key, value) => {
    if (!selectedNode) return;
    
    setNodes((nds) =>
      nds.map((node) => {
        if (node.id === selectedNode.id) {
          const newData = { ...node.data, [key]: value };
          // Update selected node as well to reflect changes in UI immediately
          const updatedNode = { ...node, data: newData };
          setSelectedNode(updatedNode);
          return updatedNode;
        }
        return node;
      })
    );
  };

  const addAsset = () => {
      if (!selectedNode) return;
      const currentAssets = selectedNode.data.assets || [];
      updateNodeData('assets', [...currentAssets, { type: 'package', value: '' }]);
  };

  const updateAsset = (index, field, value) => {
      if (!selectedNode) return;
      const currentAssets = [...(selectedNode.data.assets || [])];
      currentAssets[index] = { ...currentAssets[index], [field]: value };
      updateNodeData('assets', currentAssets);
  };
  
  const removeAsset = (index) => {
      if (!selectedNode) return;
      const currentAssets = [...(selectedNode.data.assets || [])];
      currentAssets.splice(index, 1);
      updateNodeData('assets', currentAssets);
  };

  // Restore deploy job on mount
  useEffect(() => {
      const savedJobId = localStorage.getItem('deployJobId');
      if (savedJobId) {
          setDeployJobId(savedJobId);
          setIsDeploying(true);
      }
  }, []);

  // Poll for deploy job status
  useEffect(() => {
      if (!deployJobId) return;

      let isMounted = true;
      let timeoutId;

      const poll = async () => {
          try {
              const jobRes = await axios.get(`${API_URL}/topology/deploy-jobs/${deployJobId}`);
              if (!isMounted) return;
              
              setDeployJob(jobRes.data);
              const status = jobRes.data?.status;
              
              if (status === 'completed' || status === 'failed') {
                  setIsDeploying(false);
                  localStorage.removeItem('deployJobId');
                  setDeployJobId(null);
                  
                  const result = jobRes.data?.result;
                  const results = result?.results || [];
                  const errors = results.filter(r => r.status === 'error');
                  const successes = results.filter(r => r.status === 'success');

                  let message = `Deployment finished!\n`;
                  message += `Successful VMs: ${successes.length}\n`;
                  message += `Failed VMs: ${errors.length}\n`;
                  if (errors.length > 0) {
                      message += "\nErrors:\n";
                      errors.forEach(e => {
                          message += `- ${e.node || e.name || 'Unknown Node'}: ${e.message || e.detail || 'error'}\n`;
                      });
                  }
                  setMessageModal({ isOpen: true, title: 'Deployment Finished', message: message, type: errors.length > 0 ? 'error' : 'success' });
              } else {
                  timeoutId = setTimeout(poll, 1000);
              }
          } catch (e) {
              console.error("Poll error:", e);
              if (isMounted) {
                   if (e.response && e.response.status === 404) {
                       setIsDeploying(false);
                       localStorage.removeItem('deployJobId');
                       setDeployJobId(null);
                   } else {
                       timeoutId = setTimeout(poll, 2000);
                   }
              }
          }
      };

      poll();

      return () => { 
          isMounted = false; 
          if (timeoutId) clearTimeout(timeoutId);
      };
  }, [deployJobId]);

  const handleDeploy = async () => {
      console.log("Deploy button clicked");
      
      if (nodes.length === 0) {
          setMessageModal({ isOpen: true, title: 'Warning', message: "Cannot deploy an empty topology. Please add some nodes.", type: 'error' });
          return;
      }

      // Construct topology payload
      const topology = {
          scenario: scenarioConfig,
          nodes: nodes.map(n => ({
              id: n.id,
              label: n.data.label,
              config: {
                  image: n.data.image,
                  cpu: n.data.cpu,
                  ram: n.data.ram,
                  assets: n.data.assets,
                  automation: n.data.automation || null
              }
          })),
          edges: edges.map(e => ({
              source: e.source,
              target: e.target
          }))
      };
      
      console.log("Deploying topology:", topology);
      
      // Call API
      setIsDeploying(true);
      setDeployJobError(null);
      setDeployJob(null);
      setDeployJobId(null);
      try {
          console.log(`Starting deploy job at ${API_URL}/topology/deploy-jobs`);
          const start = await axios.post(`${API_URL}/topology/deploy-jobs`, topology);
          const jobId = start.data?.job_id;
          if (!jobId) {
              throw new Error('Backend did not return a job_id');
          }
          setDeployJobId(jobId);
          localStorage.setItem('deployJobId', jobId);
      } catch (e) {
          console.error("Deployment error:", e);
          const errorMsg = e.response?.data?.detail || e.message || 'Unknown error';
          setDeployJobError(errorMsg);
          setMessageModal({ isOpen: true, title: 'Deployment Failed', message: 'Deployment failed: ' + errorMsg + "\n\nCheck console for details.", type: 'error' });
          setIsDeploying(false);
      }
  };

  return (
    <div className="dndflow w-full flex flex-col bg-background text-primary" style={{ height: 'calc(100vh - 100px)' }}>
      <div className="flex justify-between items-center p-4 bg-surface border-b border-border">
        <div className="flex items-center gap-4">
            <h2 className="text-xl font-bold text-primary">Network Topology Builder</h2>
            
            <div className="relative group">
                <button className="flex items-center gap-2 bg-surfaceHover hover:bg-surface px-3 py-1.5 rounded text-sm transition-colors text-primary">
                    <FileText size={14} /> Load Preset
                </button>
                <div className="absolute top-full left-0 pt-2 w-48 hidden group-hover:block z-50">
                    <div className="bg-surface border border-border rounded shadow-xl overflow-hidden">
                        <button onClick={() => loadPreset('simple-client-server')} className="block w-full text-left px-4 py-2 hover:bg-surfaceHover text-sm">Simple Client-Server</button>
                        <button onClick={() => loadPreset('iso-install-lab')} className="block w-full text-left px-4 py-2 hover:bg-surfaceHover text-sm">ISO Install Lab (Linux)</button>
                        <button onClick={() => loadPreset('sl1-2-smart-home-pv')} className="block w-full text-left px-4 py-2 hover:bg-surfaceHover text-sm">Smart Home PV (SL1-2)</button>
                        <button onClick={() => loadPreset('sl1-2-smart-home-pv-3vm')} className="block w-full text-left px-4 py-2 hover:bg-surfaceHover text-sm">Smart Home PV (SL1-2) - 3 VMs</button>
                        <button onClick={() => loadPreset('attacker-victim')} className="block w-full text-left px-4 py-2 hover:bg-surfaceHover text-sm">Attacker vs Victim (Linux)</button>
                    </div>
                </div>
            </div>

            <label className="flex items-center gap-2 bg-surfaceHover hover:bg-surface px-3 py-1.5 rounded text-sm cursor-pointer transition-colors">
                <Upload size={14} /> Upload YAML
                <input type="file" accept=".yaml,.yml" onChange={handleFileUpload} className="hidden" />
            </label>

            <button onClick={() => setShowScenarioSettings(true)} className="flex items-center gap-2 bg-accent/30 hover:bg-accent border border-accent px-3 py-1.5 rounded text-sm transition-colors text-accent">
                <Target size={14} /> Scenario Settings
            </button>
        </div>

        <button 
            onClick={handleDeploy} 
            disabled={isDeploying}
            className={`flex items-center gap-2 px-4 py-2 rounded transition-colors ${isDeploying ? 'bg-green-800 cursor-not-allowed text-secondary' : 'bg-green-600 hover:bg-green-700 text-white'}`}
        >
            {isDeploying ? (
                <>
                    <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></div>
                    Deploying...
                </>
            ) : (
                <>
                    <Play size={16} /> Deploy Network
                </>
            )}
        </button>
      </div>

            {(isDeploying || deployJob) && (
                <div className="bg-background border-b border-border px-4 py-3">
                    <div className="flex items-center justify-between gap-4">
                        <div className="text-sm">
                            <div className="text-primary font-medium">Deploy Progress</div>
                            <div className="text-secondary">
                                {deployJob?.message || (isDeploying ? 'Starting…' : '')}
                                {deployJobId ? ` (job ${deployJobId.slice(0, 8)}…)` : ''}
                            </div>
                            {deployJobError && <div className="text-red-300 mt-1">Error: {deployJobError}</div>}
                        </div>
                        <div className="text-xs text-secondary">
                            Status: {deployJob?.status || (isDeploying ? 'running' : 'idle')}
                        </div>
                    </div>

                    {deployJob?.progress?.downloads && Object.keys(deployJob.progress.downloads).length > 0 && (
                        <div className="mt-3">
                            <div className="text-xs text-secondary mb-2">Downloads</div>
                            <div className="space-y-2">
                                {Object.entries(deployJob.progress.downloads).map(([name, d]) => {
                                    const percent = typeof d?.percent === 'number' ? d.percent : 0;
                                    const status = d?.status || 'pending';
                                    const total = d?.total || 0;
                                    const current = d?.current || 0;
                                    const speed = formatSpeed(d?.speed_bps);
                                    const eta = formatEta(d?.eta_seconds);
                                    const sizeLabel = total > 0 ? `${formatBytes(current)} / ${formatBytes(total)}` : (current > 0 ? `${formatBytes(current)}` : '');
                                    const rightBits = [
                                        total > 0 ? `${percent}%` : null,
                                        sizeLabel || null,
                                        speed || null,
                                        eta ? `ETA ${eta}` : null,
                                        status ? status : null,
                                    ].filter(Boolean);
                                    const label = rightBits.join(' · ');

                                    return (
                                        <div key={name} className="bg-surface border border-border rounded p-2">
                                            <div className="flex items-center justify-between text-xs">
                                                <div className="text-primary truncate" title={name}>{name}</div>
                                                <div className="text-secondary ml-2">{label}</div>
                                            </div>
                                            <div className="mt-2 h-2 w-full bg-surfaceHover rounded overflow-hidden">
                                                <div
                                                    className="h-2 bg-blue-600"
                                                    style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
                                                />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {deployJob?.progress?.nodes && Object.keys(deployJob.progress.nodes).length > 0 && (
                        <div className="mt-3">
                            <div className="text-xs text-secondary mb-2">VMs</div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                {Object.entries(deployJob.progress.nodes).map(([id, n]) => {
                                    const status = n?.status || 'pending';
                                    const msg = n?.message;

                                    const pctMap = {
                                        pending: 0,
                                        creating: 50,
                                        running: 100,
                                        error: 100,
                                    };
                                    const percent = pctMap[status] ?? 0;

                                    return (
                                        <div key={id} className="bg-surface border border-border rounded p-2">
                                            <div className="flex items-center justify-between text-xs">
                                                <div className="text-primary truncate" title={n?.label || id}>{n?.label || id}</div>
                                                <div className={`ml-2 ${status === 'error' ? 'text-red-300' : 'text-secondary'}`}>{status}</div>
                                            </div>
                                            {msg && <div className="text-xs text-red-300 mt-1 truncate" title={msg}>{msg}</div>}
                                            <div className="mt-2 h-2 w-full bg-surfaceHover rounded overflow-hidden">
                                                <div
                                                    className={status === 'error' ? 'h-2 bg-red-600' : 'h-2 bg-green-600'}
                                                    style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
                                                />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            )}
      
      <div className="flex-grow flex h-full overflow-hidden">
        <ReactFlowProvider>
            <div className="w-64 bg-background border-r border-border p-4 flex flex-col gap-4 z-10 overflow-y-auto">
                <div className="text-secondary text-sm font-medium mb-2">Network Nodes</div>
                
                <div className="dndnode output p-3 bg-purple-900/30 border border-purple-700 rounded cursor-grab text-purple-100 hover:bg-purple-900/50 transition-colors flex items-center gap-2" onDragStart={(event) => event.dataTransfer.setData('application/reactflow', 'router')} draggable>
                    <Flag size={16} /> Router / Gateway
                </div>

                <div className="text-secondary text-sm font-medium mt-4 mb-2">Available Images</div>
                {availableImages.length === 0 && (
                    <div className="text-xs text-muted italic">No images found.</div>
                )}
                {availableImages.map((img) => (
                    <div 
                        key={img.path}
                        className="dndnode input p-3 bg-blue-900/30 border border-blue-700 rounded cursor-grab text-blue-100 hover:bg-blue-900/50 transition-colors flex items-center gap-2 mb-2" 
                        onDragStart={(event) => {
                            event.dataTransfer.setData('application/reactflow', 'vm');
                            event.dataTransfer.setData('image', img.name);
                        }} 
                        draggable
                    >
                        <Shield size={16} /> {img.name}
                    </div>
                ))}
                
                <div className="text-secondary text-sm font-medium mt-4 mb-2">Generic Nodes</div>
                <div className="dndnode input p-3 bg-surface border border-border rounded cursor-grab text-primary hover:bg-surfaceHover transition-colors flex items-center gap-2" onDragStart={(event) => event.dataTransfer.setData('application/reactflow', 'vm')} draggable>
                    <Shield size={16} /> Generic VM
                </div>
            </div>

            <div className="flex-grow h-full relative" ref={reactFlowWrapper}>
                <div className="absolute top-0 left-0 right-0 z-20 bg-background/95 border-b border-surface px-4 py-3 space-y-3">
                    <div>
                        <div className="text-sm text-primary font-semibold">Live VM IPs</div>
                        {nodes.length === 0 && <div className="text-xs text-secondary">No nodes yet.</div>}
                        {nodes.length > 0 && (
                            <div className="grid md:grid-cols-2 gap-2 mt-2">
                                {nodes.map(n => {
                                    const info = vmInfoForNode(n.id);
                                    const ip = primaryIp(info);
                                    return (
                                        <div key={n.id} className="bg-surface border border-border rounded p-2 text-xs text-primary flex justify-between">
                                            <div className="truncate" title={n.data.label}>{n.data.label}</div>
                                            <div className="text-secondary ml-2" title={info ? (ip || 'No IP yet') : 'VM not found'}>
                                                {info ? (ip || 'IP pending') : 'not deployed'}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>

                    {edges.length > 0 && (
                        <div>
                            <div className="text-sm text-primary font-semibold">Connections</div>
                            <div className="grid md:grid-cols-2 gap-2 mt-2 text-xs text-primary">
                                {edges.map(e => {
                                    const src = nodes.find(n => n.id === e.source);
                                    const dst = nodes.find(n => n.id === e.target);
                                    const srcIp = primaryIp(vmInfoForNode(e.source));
                                    const dstIp = primaryIp(vmInfoForNode(e.target));
                                    return (
                                        <div key={e.id} className="bg-surface border border-border rounded px-2 py-1 flex justify-between items-center">
                                            <div className="truncate" title={src?.data?.label || e.source}>{src?.data?.label || e.source} {srcIp ? `(${srcIp})` : ''}</div>
                                            <div className="text-secondary mx-2">↔</div>
                                            <div className="truncate text-right" title={dst?.data?.label || e.target}>{dst?.data?.label || e.target} {dstIp ? `(${dstIp})` : ''}</div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onConnect={onConnect}
                    onInit={setReactFlowInstance}
                    onDrop={onDrop}
                    onDragOver={onDragOver}
                    onNodeClick={onNodeClick}
                    onMove={() => {
                        // Save viewport position as user moves around
                        if (reactFlowInstance && viewportRestored) {
                            const saved = localStorage.getItem('networkTopology');
                            if (saved) {
                                try {
                                    const topology = JSON.parse(saved);
                                    topology.viewport = reactFlowInstance.getViewport();
                                    localStorage.setItem('networkTopology', JSON.stringify(topology));
                                } catch (err) {
                                    // Silently fail to avoid console spam
                                }
                            }
                        }
                    }}
                    nodeTypes={nodeTypes}
                    fitView={false}
                    className="bg-background"
                >
                    <Controls />
                    <Background color="#333" gap={16} />
                </ReactFlow>
            </div>

            {showScenarioSettings && (
                <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
                    <div className="bg-surface p-6 rounded-xl border border-border w-full max-w-md">
                        <h3 className="text-xl font-bold mb-4 text-primary">Scenario Configuration</h3>
                        
                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm text-secondary mb-1">Scenario Name</label>
                                <input 
                                    type="text" 
                                    value={scenarioConfig.name}
                                    onChange={(e) => setScenarioConfig({...scenarioConfig, name: e.target.value})}
                                    className="w-full bg-background border border-border rounded p-2 text-primary"
                                />
                            </div>

                            <div>
                                <label className="block text-sm text-secondary mb-1">Network Prefix (optional)</label>
                                <input
                                    type="text"
                                    value={scenarioConfig.network_prefix || ''}
                                    onChange={(e) => setScenarioConfig({ ...scenarioConfig, network_prefix: e.target.value })}
                                    placeholder="Leave blank for a random per-deploy network name"
                                    className="w-full bg-background border border-border rounded p-2 text-primary"
                                />
                                <div className="text-xs text-secondary mt-1">
                                    If set, libvirt networks will be named like <span className="font-mono">cyberange-&lt;prefix&gt;-c0</span>.
                                </div>
                            </div>
                            
                            <div>
                                <label className="block text-sm text-secondary mb-1">Team / Type</label>
                                <select 
                                    value={scenarioConfig.team}
                                    onChange={(e) => setScenarioConfig({...scenarioConfig, team: e.target.value})}
                                    className="w-full bg-background border border-border rounded p-2 text-primary"
                                >
                                    <option value="blue">Blue Team (Defense)</option>
                                    <option value="red">Red Team (Offense)</option>
                                    <option value="green">Green Team (Forensics/Infra)</option>
                                </select>
                            </div>

                            <div>
                                <label className="block text-sm text-secondary mb-1">Difficulty</label>
                                <select 
                                    value={scenarioConfig.difficulty}
                                    onChange={(e) => setScenarioConfig({...scenarioConfig, difficulty: e.target.value})}
                                    className="w-full bg-background border border-border rounded p-2 text-primary"
                                >
                                    <option value="easy">Easy</option>
                                    <option value="medium">Medium</option>
                                    <option value="hard">Hard</option>
                                    <option value="expert">Expert</option>
                                </select>
                            </div>

                            <div>
                                <label className="block text-sm text-secondary mb-1">Objective / Description</label>
                                <textarea 
                                    value={scenarioConfig.objective}
                                    onChange={(e) => setScenarioConfig({...scenarioConfig, objective: e.target.value})}
                                    className="w-full bg-background border border-border rounded p-2 h-32 text-primary"
                                />
                            </div>
                        </div>

                        <div className="flex justify-end mt-6">
                            <button onClick={() => setShowScenarioSettings(false)} className="bg-accent hover:bg-accentHover text-primary px-4 py-2 rounded">
                                Save Configuration
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {selectedNode && (
                <div className="w-80 bg-background border-l border-border p-4 overflow-y-auto z-10 shadow-xl">
                    <div className="flex justify-between items-center mb-4">
                        <h3 className="text-lg font-semibold text-primary">Configuration</h3>
                        <button onClick={() => setSelectedNode(null)} className="text-secondary hover:text-primary text-xl">&times;</button>
                    </div>
                    
                    <div className="space-y-4">
                        <div>
                            <label className="block text-sm text-secondary mb-1">Node Name</label>
                            <input 
                                type="text" 
                                value={selectedNode.data.label} 
                                onChange={(e) => updateNodeData('label', e.target.value)}
                                className="w-full bg-surface border border-border rounded p-2 text-primary focus:border-accent outline-none"
                            />
                        </div>
                        
                        <div>
                            <label className="block text-sm text-secondary mb-1">OS Image</label>
                            <select 
                                value={selectedNode.data.image} 
                                onChange={(e) => updateNodeData('image', e.target.value)}
                                className="w-full bg-surface border border-border rounded p-2 text-primary focus:border-accent outline-none"
                            >
                                <option value="ubuntu-20.04">Ubuntu 20.04 LTS</option>
                                <option value="kali-linux">Kali Linux</option>
                                <option value="windows-10">Windows 10</option>
                                <option value="gateway">Gateway/Router</option>
                                {availableImages.map(img => (
                                    <option key={img.path} value={img.name}>{img.name} (Custom)</option>
                                ))}
                            </select>
                        </div>

                        <div className="grid grid-cols-2 gap-2">
                            <div>
                                <label className="block text-sm text-secondary mb-1">CPU Cores</label>
                                <input 
                                    type="number" 
                                    value={selectedNode.data.cpu} 
                                    onChange={(e) => updateNodeData('cpu', parseInt(e.target.value))}
                                    className="w-full bg-surface border border-border rounded p-2 text-primary focus:border-accent outline-none"
                                />
                            </div>
                            <div>
                                <label className="block text-sm text-secondary mb-1">RAM (MB)</label>
                                <input 
                                    type="number" 
                                    value={selectedNode.data.ram} 
                                    onChange={(e) => updateNodeData('ram', parseInt(e.target.value))}
                                    className="w-full bg-surface border border-border rounded p-2 text-primary focus:border-accent outline-none"
                                />
                            </div>
                        </div>

                        <div className="border-t border-border pt-4">
                            <div className="flex justify-between items-center mb-2">
                                <label className="block text-sm text-secondary">Assets & Scripts</label>
                                <button onClick={addAsset} className="text-xs bg-accent px-2 py-1 rounded text-primary hover:bg-accentHover flex items-center gap-1">
                                    <Plus size={12} /> Add
                                </button>
                            </div>
                            
                            <div className="space-y-2">
                                {selectedNode.data.assets && selectedNode.data.assets.map((asset, idx) => (
                                    <div key={idx} className="bg-surface p-2 rounded border border-border">
                                        <div className="flex gap-2 mb-2">
                                            <select 
                                                value={asset.type}
                                                onChange={(e) => updateAsset(idx, 'type', e.target.value)}
                                                className="bg-surfaceHover text-xs rounded p-1 text-primary border border-border"
                                            >
                                                <option value="package">Install Package</option>
                                                <option value="command">Run Command</option>
                                            </select>
                                            <button onClick={() => removeAsset(idx)} className="ml-auto text-red-400 hover:text-red-300">
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                        <input 
                                            type="text" 
                                            value={asset.value}
                                            onChange={(e) => updateAsset(idx, 'value', e.target.value)}
                                            placeholder={asset.type === 'package' ? 'e.g. nginx' : 'e.g. systemctl start nginx'}
                                            className="w-full bg-surfaceHover border border-border rounded p-1 text-sm text-primary focus:border-accent outline-none"
                                        />
                                    </div>
                                ))}
                                {(!selectedNode.data.assets || selectedNode.data.assets.length === 0) && (
                                    <div className="text-xs text-secondary italic text-center py-2">No assets defined</div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </ReactFlowProvider>
      </div>

      <Modal
        isOpen={messageModal.isOpen}
        onClose={() => setMessageModal({ ...messageModal, isOpen: false })}
        title={messageModal.title}
        footer={
            <button onClick={() => setMessageModal({ ...messageModal, isOpen: false })} className="px-4 py-2 bg-surface hover:bg-surfaceHover text-primary rounded">Close</button>
        }
      >
        <div className={`text-sm whitespace-pre-wrap ${messageModal.type === 'error' ? 'text-red-400' : messageModal.type === 'success' ? 'text-green-400' : 'text-secondary'}`}>
            {messageModal.message}
        </div>
      </Modal>
    </div>
  );
};

export default NetworkBuilder;
