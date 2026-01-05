import React, { useState } from 'react';
import { Plus, Trash2, Save, ArrowLeft } from 'lucide-react';
import axios from 'axios';

const getApiUrl = () => {
  const hostname = window.location.hostname;
  return `http://${hostname}:8001/api`;
};

function TrainingEditor({ training, onSave, onCancel }) {
  const [editedTraining, setEditedTraining] = useState(training);
  const API_URL = getApiUrl();

  const handleLevelChange = (index, field, value) => {
    const newLevels = [...editedTraining.levels];
    newLevels[index] = { ...newLevels[index], [field]: value };
    setEditedTraining({ ...editedTraining, levels: newLevels });
  };

  const addLevel = () => {
    setEditedTraining({
      ...editedTraining,
      levels: [
        ...editedTraining.levels,
        { id: Date.now().toString(), title: 'New Level', description: '', tasks: [] }
      ]
    });
  };

  const removeLevel = (index) => {
    const newLevels = editedTraining.levels.filter((_, i) => i !== index);
    setEditedTraining({ ...editedTraining, levels: newLevels });
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
      await axios.put(`${API_URL}/trainings/${editedTraining.id}`, editedTraining);
      onSave();
    } catch (e) {
      alert("Failed to save training");
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex justify-between items-center mb-6">
        <button onClick={onCancel} className="text-secondary hover:text-white flex items-center">
          <ArrowLeft className="mr-2" /> Back
        </button>
        <h2 className="text-2xl font-bold">Editing: {editedTraining.title}</h2>
        <button onClick={save} className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded flex items-center">
          <Save className="mr-2" size={18} /> Save Changes
        </button>
      </div>

      <div className="flex-1 overflow-auto space-y-8">
        {/* General Info */}
        <div className="bg-surface p-6 rounded-xl border border-border">
          <h3 className="text-lg font-bold mb-4">General Information</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-secondary mb-1">Title</label>
              <input 
                value={editedTraining.title} 
                onChange={e => setEditedTraining({...editedTraining, title: e.target.value})}
                className="w-full bg-background border border-border rounded p-2 text-white"
              />
            </div>
            <div>
              <label className="block text-sm text-secondary mb-1">Difficulty</label>
              <select 
                value={editedTraining.difficulty}
                onChange={e => setEditedTraining({...editedTraining, difficulty: e.target.value})}
                className="w-full bg-background border border-border rounded p-2 text-white"
              >
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm text-secondary mb-1">Description</label>
              <textarea 
                value={editedTraining.description}
                onChange={e => setEditedTraining({...editedTraining, description: e.target.value})}
                className="w-full bg-background border border-border rounded p-2 text-white"
                rows={3}
              />
            </div>
          </div>
        </div>

        {/* Levels */}
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-xl font-bold">Levels</h3>
            <button onClick={addLevel} className="bg-accent hover:bg-accentHover text-white px-3 py-1 rounded flex items-center text-sm">
              <Plus size={16} className="mr-1" /> Add Level
            </button>
          </div>

          {editedTraining.levels.map((level, lIdx) => (
            <div key={level.id} className="bg-surface p-6 rounded-xl border border-border">
              <div className="flex justify-between items-start mb-4">
                <h4 className="font-bold text-lg">Level {lIdx + 1}</h4>
                <button onClick={() => removeLevel(lIdx)} className="text-red-400 hover:text-red-300">
                  <Trash2 size={18} />
                </button>
              </div>

              <div className="space-y-4 mb-6">
                <input 
                  value={level.title}
                  onChange={e => handleLevelChange(lIdx, 'title', e.target.value)}
                  placeholder="Level Title"
                  className="w-full bg-background border border-border rounded p-2 text-white font-bold"
                />
                <textarea 
                  value={level.description}
                  onChange={e => handleLevelChange(lIdx, 'description', e.target.value)}
                  placeholder="Level Description"
                  className="w-full bg-background border border-border rounded p-2 text-white"
                  rows={2}
                />
              </div>

              {/* Tasks */}
              <div className="pl-4 border-l-2 border-border space-y-4">
                <div className="flex justify-between items-center">
                  <h5 className="font-bold text-sm text-secondary">Tasks</h5>
                  <button onClick={() => addTask(lIdx)} className="text-accent hover:text-blue-300 text-xs flex items-center">
                    <Plus size={14} className="mr-1" /> Add Task
                  </button>
                </div>

                {level.tasks.map((task, tIdx) => (
                  <div key={task.id} className="bg-background p-4 rounded border border-border">
                    <div className="flex justify-between mb-2">
                      <span className="text-xs text-secondary">Task {tIdx + 1}</span>
                      <button onClick={() => removeTask(lIdx, tIdx)} className="text-red-400 hover:text-red-300">
                        <Trash2 size={14} />
                      </button>
                    </div>
                    <div className="space-y-2">
                      <input 
                        value={task.question}
                        onChange={e => updateTask(lIdx, tIdx, 'question', e.target.value)}
                        placeholder="Question / Instruction"
                        className="w-full bg-surface border border-border rounded p-2 text-sm text-white"
                      />
                      <div className="flex space-x-2">
                        <select 
                          value={task.type}
                          onChange={e => updateTask(lIdx, tIdx, 'type', e.target.value)}
                          className="bg-surface border border-border rounded p-2 text-sm text-white"
                        >
                          <option value="quiz">Quiz (Text Answer)</option>
                          <option value="action">Action (Manual Verify)</option>
                        </select>
                        {task.type === 'quiz' && (
                          <input 
                            value={task.answer}
                            onChange={e => updateTask(lIdx, tIdx, 'answer', e.target.value)}
                            placeholder="Correct Answer"
                            className="flex-1 bg-surface border border-border rounded p-2 text-sm text-white"
                          />
                        )}
                      </div>
                      <input 
                        value={task.hints.join(', ')}
                        onChange={e => updateTask(lIdx, tIdx, 'hints', e.target.value.split(', '))}
                        placeholder="Hints (comma separated)"
                        className="w-full bg-surface border border-border rounded p-2 text-sm text-white"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default TrainingEditor;
