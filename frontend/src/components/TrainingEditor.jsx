import React, { useState } from 'react';
import { Plus, Trash2, Save, ArrowLeft, Settings, Layers, FileText, HelpCircle, CheckSquare, Monitor } from 'lucide-react';
import axios from 'axios';
import Modal from './Modal';
import { getApiUrl } from '../lib/api';

function TrainingEditor({ training, onSave, onCancel }) {
  const [editedTraining, setEditedTraining] = useState(training);
  const [activeView, setActiveView] = useState('general'); // 'general' or level index
  const [messageModal, setMessageModal] = useState({ isOpen: false, title: '', message: '', type: 'info' });
  const API_URL = getApiUrl();

  const handleLevelChange = (index, field, value) => {
    const newLevels = [...editedTraining.levels];
    newLevels[index] = { ...newLevels[index], [field]: value };
    setEditedTraining({ ...editedTraining, levels: newLevels });
  };

  const addLevel = () => {
    const newLevel = { 
        id: Date.now().toString(), 
        title: 'New Level', 
        description: '', 
        vm_config: { image: 'ubuntu-20.04', cpu: 2, ram: 2048 },
        tasks: [] 
    };
    const newLevels = [...editedTraining.levels, newLevel];
    setEditedTraining({ ...editedTraining, levels: newLevels });
    setActiveView(newLevels.length - 1); // Switch to new level
  };

  const removeLevel = (index, e) => {
    e.stopPropagation();
    const newLevels = editedTraining.levels.filter((_, i) => i !== index);
    setEditedTraining({ ...editedTraining, levels: newLevels });
    if (activeView === index) setActiveView('general');
    else if (typeof activeView === 'number' && activeView > index) setActiveView(activeView - 1);
  };

  const addTask = (levelIndex) => {
    const newLevels = [...editedTraining.levels];
    newLevels[levelIndex].tasks.push({
      id: Date.now().toString(),
      question: 'New Question',
      type: 'quiz',
      answer: '',
      hints: []
    });
    setEditedTraining({ ...editedTraining, levels: newLevels });
  };

  const updateTask = (levelIndex, taskIndex, field, value) => {
    const newLevels = [...editedTraining.levels];
    newLevels[levelIndex].tasks[taskIndex] = { ...newLevels[levelIndex].tasks[taskIndex], [field]: value };
    setEditedTraining({ ...editedTraining, levels: newLevels });
  };

  const removeTask = (levelIndex, taskIndex) => {
    const newLevels = [...editedTraining.levels];
    newLevels[levelIndex].tasks = newLevels[levelIndex].tasks.filter((_, i) => i !== taskIndex);
    setEditedTraining({ ...editedTraining, levels: newLevels });
  };

  const save = async () => {
    try {
      if (editedTraining.id) {
          await axios.put(`${API_URL}/trainings/${editedTraining.id}`, editedTraining);
      } else {
          await axios.post(`${API_URL}/trainings`, editedTraining);
      }
      onSave();
    } catch (e) {
      setMessageModal({ isOpen: true, title: 'Error', message: 'Failed to save training', type: 'error' });
    }
  };

  return (
    <div className="h-full flex flex-col bg-background text-primary">
      {/* Header */}
      <div className="flex justify-between items-center p-4 border-b border-border bg-surface">
        <div className="flex items-center gap-4">
            <button onClick={onCancel} className="text-secondary hover:text-primary flex items-center transition-colors">
            <ArrowLeft className="mr-2" size={20} /> Back
            </button>
            <div className="h-6 w-px bg-border"></div>
            <h2 className="text-xl font-bold truncate max-w-md">{editedTraining.title || 'New Training'}</h2>
        </div>
        <button onClick={save} className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded flex items-center transition-colors shadow-lg shadow-green-900/20">
          <Save className="mr-2" size={18} /> Save Training
        </button>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <div className="w-64 bg-surface border-r border-border flex flex-col">
            <div className="p-4 border-b border-border">
                <div 
                    className={`flex items-center gap-3 p-3 rounded cursor-pointer transition-colors ${activeView === 'general' ? 'bg-accent text-white' : 'hover:bg-surfaceHover text-secondary hover:text-primary'}`}
                    onClick={() => setActiveView('general')}
                >
                    <Settings size={18} />
                    <span className="font-medium">General Settings</span>
                </div>
            </div>
            
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
                <div className="text-xs font-bold text-secondary uppercase tracking-wider mb-2 px-2">Levels</div>
                {editedTraining.levels.map((level, idx) => (
                    <div 
                        key={level.id}
                        className={`group flex items-center justify-between p-3 rounded cursor-pointer transition-colors ${activeView === idx ? 'bg-accent/20 text-accent border border-accent/50' : 'hover:bg-surfaceHover text-primary border border-transparent'}`}
                        onClick={() => setActiveView(idx)}
                    >
                        <div className="flex items-center gap-3 overflow-hidden">
                            <Layers size={16} className="flex-shrink-0" />
                            <div className="truncate text-sm font-medium">
                                {level.title || `Level ${idx + 1}`}
                            </div>
                        </div>
                        <button 
                            onClick={(e) => removeLevel(idx, e)}
                            className="opacity-0 group-hover:opacity-100 text-secondary hover:text-red-400 transition-opacity p-1"
                        >
                            <Trash2 size={14} />
                        </button>
                    </div>
                ))}
                
                <button 
                    onClick={addLevel}
                    className="w-full flex items-center justify-center gap-2 p-3 rounded border border-dashed border-border text-secondary hover:text-primary hover:border-secondary hover:bg-surfaceHover transition-all mt-4"
                >
                    <Plus size={16} /> Add Level
                </button>
            </div>
        </div>

        {/* Main Content */}
        <div className="flex-1 overflow-y-auto bg-background p-8">
            <div className="max-w-4xl mx-auto">
                {activeView === 'general' ? (
                    <div className="space-y-6 animate-in fade-in duration-300">
                        <h3 className="text-2xl font-bold mb-6 flex items-center gap-2">
                            <Settings className="text-accent" /> General Configuration
                        </h3>
                        
                        <div className="bg-surface p-6 rounded-xl border border-border space-y-6">
                            <div>
                                <label className="block text-sm font-medium text-secondary mb-2">Training Title</label>
                                <input 
                                    value={editedTraining.title} 
                                    onChange={e => setEditedTraining({...editedTraining, title: e.target.value})}
                                    className="w-full bg-background border border-border rounded-lg p-3 text-primary focus:border-accent outline-none transition-colors"
                                    placeholder="e.g. Web Security 101"
                                />
                            </div>
                            
                            <div className="grid grid-cols-2 gap-6">
                                <div>
                                    <label className="block text-sm font-medium text-secondary mb-2">Difficulty Level</label>
                                    <select 
                                        value={editedTraining.difficulty}
                                        onChange={e => setEditedTraining({...editedTraining, difficulty: e.target.value})}
                                        className="w-full bg-background border border-border rounded-lg p-3 text-primary focus:border-accent outline-none transition-colors"
                                    >
                                        <option value="easy">Easy</option>
                                        <option value="medium">Medium</option>
                                        <option value="hard">Hard</option>
                                        <option value="expert">Expert</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-secondary mb-2">Estimated Duration</label>
                                    <input 
                                        type="text"
                                        placeholder="e.g. 30 mins"
                                        className="w-full bg-background border border-border rounded-lg p-3 text-primary focus:border-accent outline-none transition-colors"
                                    />
                                </div>
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-secondary mb-2">Description</label>
                                <textarea 
                                    value={editedTraining.description}
                                    onChange={e => setEditedTraining({...editedTraining, description: e.target.value})}
                                    className="w-full bg-background border border-border rounded-lg p-3 text-primary focus:border-accent outline-none transition-colors min-h-[150px]"
                                    placeholder="Describe what students will learn in this module..."
                                />
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="space-y-8 animate-in fade-in duration-300">
                        <div className="flex items-center justify-between">
                            <h3 className="text-2xl font-bold flex items-center gap-2">
                                <Layers className="text-accent" /> Level {activeView + 1} Configuration
                            </h3>
                        </div>

                        {/* Level Details */}
                        <div className="bg-surface p-6 rounded-xl border border-border space-y-6">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                <div className="md:col-span-2">
                                    <label className="block text-sm font-medium text-secondary mb-2">Level Title</label>
                                    <input 
                                        value={editedTraining.levels[activeView].title}
                                        onChange={e => handleLevelChange(activeView, 'title', e.target.value)}
                                        className="w-full bg-background border border-border rounded-lg p-3 text-primary focus:border-accent outline-none transition-colors font-bold text-lg"
                                        placeholder="e.g. Introduction to SQL Injection"
                                    />
                                </div>
                                <div className="md:col-span-2">
                                    <label className="block text-sm font-medium text-secondary mb-2">Level Description / Instructions</label>
                                    <textarea 
                                        value={editedTraining.levels[activeView].description}
                                        onChange={e => handleLevelChange(activeView, 'description', e.target.value)}
                                        className="w-full bg-background border border-border rounded-lg p-3 text-primary focus:border-accent outline-none transition-colors min-h-[100px]"
                                        placeholder="Provide instructions for the student..."
                                    />
                                </div>
                            </div>
                        </div>

                        {/* VM Configuration */}
                        <div className="bg-surface p-6 rounded-xl border border-border space-y-6">
                            <h4 className="text-lg font-bold flex items-center gap-2 text-primary">
                                <Monitor size={20} /> Environment Configuration
                            </h4>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                <div>
                                    <label className="block text-sm font-medium text-secondary mb-2">Base Image</label>
                                    <select 
                                        value={editedTraining.levels[activeView].vm_config?.image || 'ubuntu-20.04'}
                                        onChange={e => handleLevelChange(activeView, 'vm_config', { ...editedTraining.levels[activeView].vm_config, image: e.target.value })}
                                        className="w-full bg-background border border-border rounded-lg p-3 text-primary focus:border-accent outline-none transition-colors"
                                    >
                                        <option value="ubuntu-20.04">Ubuntu 20.04 LTS</option>
                                        <option value="kali-linux">Kali Linux</option>
                                        <option value="windows-10">Windows 10</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-secondary mb-2">CPU Cores</label>
                                    <input 
                                        type="number"
                                        value={editedTraining.levels[activeView].vm_config?.cpu || 2}
                                        onChange={e => handleLevelChange(activeView, 'vm_config', { ...editedTraining.levels[activeView].vm_config, cpu: parseInt(e.target.value) })}
                                        className="w-full bg-background border border-border rounded-lg p-3 text-primary focus:border-accent outline-none transition-colors"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-secondary mb-2">RAM (MB)</label>
                                    <input 
                                        type="number"
                                        value={editedTraining.levels[activeView].vm_config?.ram || 2048}
                                        onChange={e => handleLevelChange(activeView, 'vm_config', { ...editedTraining.levels[activeView].vm_config, ram: parseInt(e.target.value) })}
                                        className="w-full bg-background border border-border rounded-lg p-3 text-primary focus:border-accent outline-none transition-colors"
                                    />
                                </div>
                            </div>
                        </div>

                        {/* Tasks */}
                        <div className="space-y-4">
                            <div className="flex justify-between items-center">
                                <h4 className="text-lg font-bold flex items-center gap-2 text-primary">
                                    <CheckSquare size={20} /> Tasks & Questions
                                </h4>
                                <button onClick={() => addTask(activeView)} className="text-accent hover:text-accentHover text-sm font-medium flex items-center gap-1 transition-colors">
                                    <Plus size={16} /> Add Task
                                </button>
                            </div>

                            {editedTraining.levels[activeView].tasks.length === 0 && (
                                <div className="text-center py-8 border-2 border-dashed border-border rounded-xl text-secondary">
                                    <HelpCircle size={32} className="mx-auto mb-2 opacity-50" />
                                    <p>No tasks defined for this level yet.</p>
                                    <button onClick={() => addTask(activeView)} className="text-accent hover:underline mt-2">Add your first task</button>
                                </div>
                            )}

                            {editedTraining.levels[activeView].tasks.map((task, tIdx) => (
                                <div key={task.id} className="bg-surface p-6 rounded-xl border border-border hover:border-accent/50 transition-colors group">
                                    <div className="flex justify-between items-start mb-4">
                                        <div className="flex items-center gap-2">
                                            <span className="bg-background text-secondary text-xs font-bold px-2 py-1 rounded border border-border">TASK {tIdx + 1}</span>
                                            <select 
                                                value={task.type}
                                                onChange={e => updateTask(activeView, tIdx, 'type', e.target.value)}
                                                className="bg-background border border-border rounded text-xs p-1 text-primary focus:border-accent outline-none"
                                            >
                                                <option value="quiz">Quiz Question</option>
                                                <option value="action">Manual Action</option>
                                                <option value="flag">Capture The Flag</option>
                                            </select>
                                        </div>
                                        <button onClick={() => removeTask(activeView, tIdx)} className="text-secondary hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100">
                                            <Trash2 size={16} />
                                        </button>
                                    </div>

                                    <div className="space-y-4">
                                        <div>
                                            <input 
                                                value={task.question}
                                                onChange={e => updateTask(activeView, tIdx, 'question', e.target.value)}
                                                placeholder="Enter the question or instruction here..."
                                                className="w-full bg-background border border-border rounded-lg p-3 text-primary focus:border-accent outline-none transition-colors"
                                            />
                                        </div>

                                        {task.type !== 'action' && (
                                            <div>
                                                <label className="block text-xs font-medium text-secondary mb-1 uppercase tracking-wider">Correct Answer / Flag</label>
                                                <input 
                                                    value={task.answer}
                                                    onChange={e => updateTask(activeView, tIdx, 'answer', e.target.value)}
                                                    placeholder={task.type === 'flag' ? 'flag{...}' : 'Expected answer'}
                                                    className="w-full bg-background border border-border rounded-lg p-3 text-primary font-mono text-sm focus:border-accent outline-none transition-colors"
                                                />
                                            </div>
                                        )}

                                        <div>
                                            <label className="block text-xs font-medium text-secondary mb-1 uppercase tracking-wider">Hints (Optional)</label>
                                            <div className="flex gap-2">
                                                <input 
                                                    value={task.hints.join(', ')}
                                                    onChange={e => updateTask(activeView, tIdx, 'hints', e.target.value.split(', '))}
                                                    placeholder="Comma separated hints..."
                                                    className="flex-1 bg-background border border-border rounded-lg p-3 text-sm text-primary focus:border-accent outline-none transition-colors"
                                                />
                                            </div>
                                            <p className="text-[10px] text-secondary mt-1">Separate multiple hints with commas.</p>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
      </div>

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
    </div>
  );
}

export default TrainingEditor;
