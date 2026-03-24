import React, { useState, useEffect, useRef } from 'react';
import { BookOpen, CheckCircle, Play, ChevronRight, Award, Plus, Edit, Trash2, Monitor, XCircle, Upload, Lightbulb } from 'lucide-react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import TrainingEditor from './TrainingEditor';
import VNCViewer from './VNCViewer';
import Modal from './Modal';
import { getApiUrl } from '../lib/api';

function Training() {
  const [trainings, setTrainings] = useState([]);
  const [activeTraining, setActiveTraining] = useState(null);
  const [editingTraining, setEditingTraining] = useState(null);
  const [currentLevelIndex, setCurrentLevelIndex] = useState(0);
  const [answers, setAnswers] = useState({});
  const [vmStatus, setVmStatus] = useState(null);
  const [deploying, setDeploying] = useState(false);
    const [runId, setRunId] = useState(null);
    const [runEvents, setRunEvents] = useState([]);
    const [completedTasks, setCompletedTasks] = useState(new Set());
    const [pendingNextLevel, setPendingNextLevel] = useState(null);
    const wsRef = useRef(null);
    const wsReconnectTimer = useRef(null);

    // Modal States
    const [deleteConfirm, setDeleteConfirm] = useState({ isOpen: false, trainingId: null });
    const [destroyConfirm, setDestroyConfirm] = useState(false);
    const [consolePrompt, setConsolePrompt] = useState({ isOpen: false, value: 'Hello from UI' });
    const [messageModal, setMessageModal] = useState({ isOpen: false, title: '', message: '', type: 'info' });

  const API_URL = getApiUrl();

  useEffect(() => {
    fetchTrainings();
  }, []);

  useEffect(() => {
    if (activeTraining && activeTraining.levels[currentLevelIndex]) {
        checkVmStatus();
    } else {
        setVmStatus(null);
    }
  }, [activeTraining, currentLevelIndex]);

  const fetchTrainings = async () => {
    try {
      const res = await axios.get(`${API_URL}/trainings`);
      setTrainings(res.data);
    } catch (e) {
      console.error("Failed to fetch trainings", e);
    }
  };

  const checkVmStatus = async () => {
      if (!activeTraining) return;
      try {
          const res = await axios.get(`${API_URL}/trainings/${activeTraining.id}/levels/${currentLevelIndex}/status`);
          setVmStatus(res.data);
      } catch (e) {
          console.error("Failed to check VM status", e);
      }
  };

  const deployEnvironment = async () => {
      setDeploying(true);
      try {
          const res = await axios.post(`${API_URL}/trainings/${activeTraining.id}/levels/${currentLevelIndex}/deploy`);
          setVmStatus({ vms: res.data.vms }); // Optimistic update or use response
          // Poll for status update to get ports if not immediately available
          setTimeout(checkVmStatus, 2000);
      } catch (e) {
          setMessageModal({ isOpen: true, title: 'Error', message: "Failed to deploy environment: " + (e.response?.data?.detail || e.message), type: 'error' });
      } finally {
          setDeploying(false);
      }
  };

  const confirmDestroyEnvironment = () => {
      setDestroyConfirm(true);
  };

  const executeDestroyEnvironment = async () => {
      try {
          await axios.post(`${API_URL}/trainings/${activeTraining.id}/levels/${currentLevelIndex}/destroy`);
          checkVmStatus();
          setDestroyConfirm(false);
      } catch (e) {
          setMessageModal({ isOpen: true, title: 'Error', message: 'Failed to destroy environment', type: 'error' });
      }
  };

    const startTraining = (training) => {
        setActiveTraining(training);
        setCurrentLevelIndex(0);
        setAnswers({});
        setVmStatus(null);
        setCompletedTasks(new Set());
        setPendingNextLevel(null);
        (async () => {
            try {
                const res = await axios.post(`${API_URL}/training-runs`, null, { params: { definition_id: training.id } });
                setRunId(res.data.id);
            } catch (e) {
                console.error('Failed to start training run', e);
            }
        })();
    };

    // Subscribe to run events via WebSocket
    useEffect(() => {
        if (!runId) return;
        let cancelled = false;

        const connectWs = () => {
            if (cancelled) return;
            // Derive WS URL from API_URL so it works with any host/port
            const wsBase = API_URL.replace(/^http/, 'ws').replace(/\/api\/?$/, '');
            const wsUrl = `${wsBase}/api/ws/training-runs/${runId}`;
            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;
            ws.onopen = () => console.log('WS open for run', runId);
            ws.onmessage = (e) => {
                try {
                    const data = JSON.parse(e.data);
                    setRunEvents(prev => [data, ...prev]);
                } catch (err) {
                    console.error('Invalid WS message', err);
                }
            };
            ws.onclose = () => {
                console.log('WS closed for run', runId);
                if (!cancelled) {
                    wsReconnectTimer.current = setTimeout(connectWs, 3000);
                }
            };
        };

        connectWs();

        return () => {
            cancelled = true;
            clearTimeout(wsReconnectTimer.current);
            try { wsRef.current?.close(); } catch (e) {}
            wsRef.current = null;
        };
    }, [runId]);

  const handleAnswerChange = (taskId, value) => {
    setAnswers({ ...answers, [taskId]: value });
  };

  const handleCloseMessageModal = () => {
    setMessageModal(prev => ({ ...prev, isOpen: false }));
    if (pendingNextLevel !== null) {
      const nextLevel = pendingNextLevel;
      setPendingNextLevel(null);
      // Keep VMs running — environment carries over to the next level
      setCurrentLevelIndex(nextLevel);
    }
  };

  const checkAnswer = async (task) => {
    const userAnswer = answers[task.id];
    if (!userAnswer || !userAnswer.trim()) {
      setMessageModal({ isOpen: true, title: 'Incorrect', message: 'Please enter an answer.', type: 'error' });
      return;
    }

    // If we have a run, submit to backend
    if (runId) {
      try {
        const res = await axios.post(`${API_URL}/training-runs/${runId}/levels/${currentLevelIndex}/submit`, {
          task_id: task.id,
          answer: userAnswer
        });
        if (res.data.correct) {
          setCompletedTasks(prev => new Set(prev).add(task.id));
          // If there's a next level, prompt user instead of auto-advancing
          if (res.data.next_level !== null && res.data.next_level !== undefined && res.data.next_level < activeTraining.levels.length) {
            setPendingNextLevel(res.data.next_level);
            setMessageModal({ isOpen: true, title: 'Correct!', message: `Score: ${res.data.score}. Click Close to proceed to the next level.`, type: 'success' });
          } else {
            setMessageModal({ isOpen: true, title: 'Correct!', message: `Score: ${res.data.score}`, type: 'success' });
          }
        } else {
          setMessageModal({ isOpen: true, title: 'Incorrect', message: 'Try again.', type: 'error' });
        }
      } catch (e) {
        setMessageModal({ isOpen: true, title: 'Error', message: 'Failed to submit answer: ' + (e.response?.data?.detail || e.message), type: 'error' });
      }
    } else {
      // Fallback local check when no run is active
      if (userAnswer.trim().toLowerCase() === (task.answer || '').trim().toLowerCase()) {
        setCompletedTasks(prev => new Set(prev).add(task.id));
        setMessageModal({ isOpen: true, title: 'Correct!', message: 'Well done!', type: 'success' });
      } else {
        setMessageModal({ isOpen: true, title: 'Incorrect', message: 'Try again.', type: 'error' });
      }
    }
  };

  const takeHint = async (task, hintIdx) => {
    if (!runId) return;
    try {
      await axios.post(`${API_URL}/training-runs/${runId}/levels/${currentLevelIndex}/hint`, null, {
        params: { hint_idx: hintIdx }
      });
    } catch (e) {
      console.error('Failed to record hint usage', e);
    }
  };

  const handleUploadTraining = async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append('file', file);

      try {
          await axios.post(`${API_URL}/trainings/upload`, formData, {
              headers: {
                  'Content-Type': 'multipart/form-data'
              }
          });
          fetchTrainings();
      } catch (err) {
          setMessageModal({ isOpen: true, title: 'Error', message: 'Failed to upload training: ' + (err.response?.data?.detail || err.message), type: 'error' });
      }
      e.target.value = null; // Reset input
  };

  const handleCreateTraining = () => {
      const newTraining = {
          title: 'New Training Scenario',
          description: '',
          difficulty: 'easy',
          levels: []
      };
      setEditingTraining(newTraining);
  };

  const handleEditTraining = (e, training) => {
    e.stopPropagation();
    setEditingTraining(training);
  };

  const handleDeleteTraining = (e, trainingId) => {
    e.stopPropagation();
    setDeleteConfirm({ isOpen: true, trainingId });
  };

  const executeDeleteTraining = async () => {
    if (!deleteConfirm.trainingId) return;
    try {
      await axios.delete(`${API_URL}/trainings/${deleteConfirm.trainingId}`);
      fetchTrainings();
      setDeleteConfirm({ isOpen: false, trainingId: null });
    } catch (err) {
      setMessageModal({ isOpen: true, title: 'Error', message: 'Failed to delete training', type: 'error' });
    }
  };

  const handleSaveEdit = () => {
    setEditingTraining(null);
    fetchTrainings();
  };

  const executeSendConsole = async () => {
      if (!consolePrompt.value) return;
      try {
          await axios.post(`${API_URL}/debug/trainings/${activeTraining.id}/levels/${currentLevelIndex}/console`, { msg: consolePrompt.value });
          setConsolePrompt({ ...consolePrompt, isOpen: false });
          setMessageModal({ isOpen: true, title: 'Success', message: 'Test console message sent', type: 'success' });
      } catch (e) {
          setMessageModal({ isOpen: true, title: 'Error', message: 'Failed to send test message: ' + (e.response?.data?.detail || e.message), type: 'error' });
      }
  };

  if (editingTraining) {
    return <TrainingEditor training={editingTraining} onSave={handleSaveEdit} onCancel={() => setEditingTraining(null)} />;
  }

  if (activeTraining) {
    const level = activeTraining.levels[currentLevelIndex];
    return (
      <div className="flex h-full">
        {/* Sidebar for levels */}
        <div className="w-64 bg-surface border-r border-border p-4 flex flex-col">
          <h3 className="font-bold text-lg mb-4 text-primary">{activeTraining.title}</h3>
          <div className="space-y-2 flex-1 overflow-y-auto">
            {activeTraining.levels.map((l, idx) => (
              <div 
                key={l.id} 
                className={`p-2 rounded cursor-pointer ${idx === currentLevelIndex ? 'bg-accent' : 'hover:bg-surfaceHover'}`}
                onClick={() => setCurrentLevelIndex(idx)}
              >
                <div className="text-sm font-medium text-primary">Level {idx + 1}</div>
                <div className="text-xs text-secondary truncate">{l.title}</div>
              </div>
            ))}
            {activeTraining.levels.length === 0 && (
                <div className="text-sm text-muted italic">No levels yet.</div>
            )}
          </div>
          <button onClick={() => setActiveTraining(null)} className="mt-4 text-sm text-secondary hover:text-white border-t border-border pt-4">
            &larr; Back to Trainings
          </button>
        </div>

        {/* Main Content */}
        <div className="flex-1 p-6 overflow-auto">
          <div className={`mx-auto transition-all duration-300 ${vmStatus?.vms?.some(vm => vm.state === 1) ? 'max-w-[95%]' : 'max-w-3xl'}`}>
            {level ? (
                <>
                    <h2 className="text-2xl font-bold mb-2">{level.title}</h2>
                    <div className="prose prose-invert prose-sm max-w-none mb-6 text-secondary [&_h1]:text-primary [&_h2]:text-primary [&_h3]:text-primary [&_h4]:text-primary [&_strong]:text-primary [&_code]:bg-background [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-accent [&_pre]:bg-background [&_pre]:border [&_pre]:border-border [&_pre]:rounded-lg [&_a]:text-accent [&_li]:text-secondary [&_ul]:list-disc [&_ol]:list-decimal">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{level.description}</ReactMarkdown>
                    </div>

                    {level.topology && (
                    <div className="bg-surface p-4 rounded-lg mb-6 border border-border">
                        <div className="flex justify-between items-center mb-4">
                            <div>
                                <h4 className="font-bold text-primary">Environment</h4>
                                <p className="text-sm text-secondary">This level requires a specific network topology.</p>
                            </div>
                            <div className="flex space-x-2">
                                {vmStatus && vmStatus.vms && vmStatus.vms.some(vm => vm.state === 1) ? (
                                    <button 
                                        onClick={confirmDestroyEnvironment}
                                        className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded flex items-center"
                                    >
                                        <XCircle size={16} className="mr-2" /> Destroy
                                    </button>
                                ) : (
                                    <button 
                                        onClick={deployEnvironment}
                                        disabled={deploying}
                                        className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded flex items-center disabled:opacity-50"
                                    >
                                        <Play size={16} className="mr-2" /> {deploying ? 'Deploying...' : 'Deploy Environment'}
                                    </button>
                                )}
                                                                <button
                                                                    onClick={() => setConsolePrompt({ isOpen: true, value: 'Hello from UI' })}
                                                                    className="bg-surface hover:bg-surfaceHover text-primary px-4 py-2 rounded"
                                                                >
                                                                    Send Test Console
                                                                </button>
                            </div>
                        </div>

                        {vmStatus && vmStatus.vms && vmStatus.vms.length > 0 && (
                            <div className="space-y-4 mt-4 border-t border-border pt-4">
                                {vmStatus.vms.map(vm => (
                                    <div key={vm.name} className="bg-background p-4 rounded border border-border">
                                        <div className="flex justify-between items-center mb-2">
                                            <span className="font-bold flex items-center text-primary">
                                                <Monitor size={16} className="mr-2" /> {vm.name}
                                            </span>
                                            <span className={`text-xs px-2 py-1 rounded ${vm.state === 1 ? 'bg-green-900 text-green-400' : vm.status === 'error' ? 'bg-red-900 text-red-400' : 'bg-gray-700 text-gray-300'}`}>
                                                {vm.state === 1 ? 'Running' : vm.status === 'error' ? 'Error' : 'Stopped'}
                                            </span>
                                        </div>
                                        {vm.credentials && (
                                            <div className="text-xs bg-blue-900/40 text-blue-300 px-3 py-2 rounded mb-2 flex items-center gap-4">
                                                <span>Login: <code className="bg-background px-1.5 py-0.5 rounded text-primary font-mono">{vm.credentials.username}</code></span>
                                                <span>Password: <code className="bg-background px-1.5 py-0.5 rounded text-primary font-mono">{vm.credentials.password}</code></span>
                                            </div>
                                        )}
                                        {vm.status === 'error' && (
                                            <div className="text-xs text-red-400 mb-2">
                                                {vm.error || "Unknown error"}
                                            </div>
                                        )}
                                        {vm.state === 1 && vm.vnc_port && (
                                            <div className="mt-2">
                                                <VNCViewer 
                                                    url={`${API_URL.replace(/^http/, 'ws')}/ws/vnc/${vm.vnc_port}`}
                                                    viewOnly={false}
                                                />
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                    )}

                                        {runEvents.length > 0 && (
                                            <div className="mt-4 bg-background p-4 rounded border border-border">
                                                <h5 className="font-bold mb-2 text-primary">Live Events</h5>
                                                <ul className="text-sm text-secondary list-disc list-inside">
                                                    {runEvents.map((ev, i) => (
                                                        <li key={i}>{ev.type} — {ev.ts ? new Date(ev.ts * 1000).toLocaleTimeString() : ''}</li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}

                    <div className="space-y-6">
                    {level.tasks.map(task => (
                        <div key={task.id} className="bg-surface p-6 rounded-xl border border-border">
                        <h4 className="font-bold mb-2 flex items-center text-primary">
                            <CheckCircle className={`mr-2 ${completedTasks.has(task.id) ? 'text-green-400' : 'text-accent'}`} size={20} />
                            Task: {task.question}
                        </h4>
                        
                        {task.type === 'quiz' && (
                            <div className="mt-4 flex space-x-2">
                            <input 
                                type="text" 
                                className="flex-1 bg-background border border-border rounded p-2 text-primary"
                                placeholder="Enter your answer..."
                                value={answers[task.id] || ''}
                                onChange={(e) => handleAnswerChange(task.id, e.target.value)}
                            />
                            <button 
                                onClick={() => checkAnswer(task)}
                                className="bg-accent hover:bg-accentHover px-4 py-2 rounded text-white"
                            >
                                Submit
                            </button>
                            </div>
                        )}
                        
                        {task.hints && task.hints.length > 0 && (
                            <div className="mt-4 text-sm text-secondary">
                            <details>
                                <summary className="cursor-pointer hover:text-primary flex items-center gap-1" onClick={() => takeHint(task, 0)}>
                                  <Lightbulb size={14} /> Need a hint? {runId && <span className="text-xs text-yellow-500">(costs 10 points)</span>}
                                </summary>
                                <ul className="list-disc list-inside mt-2 pl-2">
                                {task.hints.map((hint, i) => <li key={i}>{hint}</li>)}
                                </ul>
                            </details>
                            </div>
                        )}
                        </div>
                    ))}
                    </div>
                </>
            ) : (
                <div className="text-center text-secondary mt-20">
                    <h3 className="text-xl font-bold mb-2">No Levels Defined</h3>
                    <p>This training module doesn't have any levels yet.</p>
                </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {trainings.map(t => (
            <div key={t.id} className="bg-surface rounded-xl border border-border p-6 hover:border-accent transition-colors cursor-pointer group" onClick={() => startTraining(t)}>
            <div className="flex justify-between items-start mb-4">
                <div className={`p-3 rounded-lg ${t.difficulty === 'easy' ? 'bg-green-900/50 text-green-400' : t.difficulty === 'medium' ? 'bg-yellow-900/50 text-yellow-400' : 'bg-red-900/50 text-red-400'}`}>
                <Award size={24} />
                </div>
                <div className="flex flex-col items-end">
                    <span className="text-xs uppercase tracking-wider text-secondary font-bold mb-2">{t.difficulty}</span>
                    <div className="flex space-x-2">
                        <button 
                            onClick={(e) => handleEditTraining(e, t)}
                            className="text-secondary hover:text-primary opacity-0 group-hover:opacity-100 transition-opacity"
                            title="Edit Training"
                        >
                            <Edit size={16} />
                        </button>
                        <button 
                            onClick={(e) => handleDeleteTraining(e, t.id)}
                            className="text-secondary hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                            title="Delete Training"
                        >
                            <Trash2 size={16} />
                        </button>
                    </div>
                </div>
            </div>
            <h3 className="text-xl font-bold mb-2">{t.title}</h3>
            <p className="text-secondary text-sm mb-4 line-clamp-2">{t.description}</p>
            <div className="flex items-center text-blue-400 text-sm font-medium">
                Start Training <ChevronRight size={16} className="ml-1" />
            </div>
            </div>
        ))}
        
        {/* Create New Training Card */}
        <div 
            onClick={handleCreateTraining}
            className="bg-surface/50 rounded-xl border border-border border-dashed p-6 flex flex-col items-center justify-center text-secondary hover:text-primary hover:border-secondary cursor-pointer min-h-[200px]"
        >
            <Plus size={48} className="mb-2" />
            <span className="font-medium">Create New Training Module</span>
        </div>

        {/* Import Training Card */}
        <div 
            onClick={() => document.getElementById('training-upload').click()}
            className="bg-surface/50 rounded-xl border border-border border-dashed p-6 flex flex-col items-center justify-center text-secondary hover:text-primary hover:border-secondary cursor-pointer min-h-[200px]"
        >
            <Upload size={48} className="mb-2" />
            <span className="font-medium">Import YAML/JSON</span>
            <input 
                id="training-upload" 
                type="file" 
                accept=".yaml,.yml,.json" 
                className="hidden" 
                onChange={handleUploadTraining}
            />
        </div>
        </div>

        <Modal
            isOpen={deleteConfirm.isOpen}
            onClose={() => setDeleteConfirm({ isOpen: false, trainingId: null })}
            title="Delete Training"
            footer={
                <>
                    <button onClick={() => setDeleteConfirm({ isOpen: false, trainingId: null })} className="px-4 py-2 text-secondary hover:text-primary">Cancel</button>
                    <button onClick={executeDeleteTraining} className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded">Delete</button>
                </>
            }
        >
            <p className="text-secondary">Are you sure you want to delete this training module? This action cannot be undone.</p>
        </Modal>

        <Modal
            isOpen={destroyConfirm}
            onClose={() => setDestroyConfirm(false)}
            title="Destroy Environment"
            footer={
                <>
                    <button onClick={() => setDestroyConfirm(false)} className="px-4 py-2 text-secondary hover:text-primary">Cancel</button>
                    <button onClick={executeDestroyEnvironment} className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded">Destroy</button>
                </>
            }
        >
            <p className="text-secondary">Are you sure you want to destroy the environment? All progress in VMs will be lost.</p>
        </Modal>

        <Modal
            isOpen={consolePrompt.isOpen}
            onClose={() => setConsolePrompt({ ...consolePrompt, isOpen: false })}
            title="Send Test Console Message"
            footer={
                <>
                    <button onClick={() => setConsolePrompt({ ...consolePrompt, isOpen: false })} className="px-4 py-2 text-secondary hover:text-primary">Cancel</button>
                    <button onClick={executeSendConsole} className="px-4 py-2 bg-accent hover:bg-accentHover text-primary rounded">Send</button>
                </>
            }
        >
            <input 
                type="text" 
                className="w-full bg-background border border-border rounded p-2 text-primary"
                value={consolePrompt.value}
                onChange={(e) => setConsolePrompt({ ...consolePrompt, value: e.target.value })}
                autoFocus
            />
        </Modal>

        <Modal
            isOpen={messageModal.isOpen}
            onClose={handleCloseMessageModal}
            title={messageModal.title}
            footer={
                <button onClick={handleCloseMessageModal} className="px-4 py-2 bg-surface hover:bg-surfaceHover text-primary rounded">
                    {pendingNextLevel !== null ? 'Continue to Next Level' : 'Close'}
                </button>
            }
        >
            <div className={`text-sm ${messageModal.type === 'error' ? 'text-red-400' : messageModal.type === 'success' ? 'text-green-400' : 'text-secondary'}`}>
                {messageModal.message}
            </div>
        </Modal>
    </>
  );
}

export default Training;
