import React, { useState, useEffect } from 'react';
import { Save, RefreshCw, Trash2, Moon, Sun, Zap, Terminal } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import Modal from './Modal';

function Settings() {
  const { theme, changeTheme } = useTheme();
  const [resetConfirm, setResetConfirm] = useState(false);
  const [settings, setSettings] = useState({
    defaultCpu: 2,
    defaultRam: 2048,
    autoRefreshInterval: 5000,
    defaultDiskSize: 20,
    showHints: true,
  });

  useEffect(() => {
    const savedSettings = localStorage.getItem('appSettings');
    if (savedSettings) {
      setSettings(JSON.parse(savedSettings));
    }
  }, []);

  const handleChange = (key, value) => {
    const newSettings = { ...settings, [key]: value };
    setSettings(newSettings);
    localStorage.setItem('appSettings', JSON.stringify(newSettings));
  };

  const handleThemeChange = (newTheme) => {
    changeTheme(newTheme);
    handleChange('theme', newTheme);
  };

  const handleReset = () => {
    setResetConfirm(true);
  };

  const executeReset = () => {
    const defaults = {
      defaultCpu: 2,
      defaultRam: 2048,
      theme: 'dark',
      autoRefreshInterval: 5000,
      defaultDiskSize: 20,
      showHints: true,
    };
    setSettings(defaults);
    changeTheme('dark');
    localStorage.setItem('appSettings', JSON.stringify(defaults));
    setResetConfirm(false);
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="bg-surface rounded-xl border border-border p-6 mb-6">
        <h2 className="text-xl font-bold mb-4 flex items-center text-primary">
          <Save className="mr-2" /> General Settings
        </h2>
        
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm text-secondary mb-2">Default VM vCPUs</label>
              <input 
                type="number" 
                value={settings.defaultCpu}
                onChange={(e) => handleChange('defaultCpu', parseInt(e.target.value))}
                className="w-full bg-background border border-border rounded p-2 text-primary"
                min="1"
                max="16"
              />
            </div>
            <div>
              <label className="block text-sm text-secondary mb-2">Default VM RAM (MB)</label>
              <input 
                type="number" 
                value={settings.defaultRam}
                onChange={(e) => handleChange('defaultRam', parseInt(e.target.value))}
                className="w-full bg-background border border-border rounded p-2 text-primary"
                step="512"
                min="512"
              />
            </div>
            <div>
              <label className="block text-sm text-secondary mb-2">Default Disk Size (GB)</label>
              <input 
                type="number" 
                value={settings.defaultDiskSize || 20}
                onChange={(e) => handleChange('defaultDiskSize', parseInt(e.target.value))}
                className="w-full bg-background border border-border rounded p-2 text-primary"
                min="10"
                max="1000"
              />
            </div>
            <div>
              <label className="block text-sm text-secondary mb-2">Dashboard Auto-Refresh Interval (ms)</label>
              <input 
                type="number" 
                value={settings.autoRefreshInterval}
                onChange={(e) => handleChange('autoRefreshInterval', parseInt(e.target.value))}
                className="w-full bg-background border border-border rounded p-2 text-primary"
                step="1000"
                min="1000"
              />
            </div>
          </div>

          <div className="flex items-center justify-between p-4 bg-background rounded-lg border border-border">
            <span className="text-secondary">Show Hints in Training</span>
            <input 
              type="checkbox"
              checked={settings.showHints !== false}
              onChange={(e) => handleChange('showHints', e.target.checked)}
              className="w-5 h-5 accent-accent"
            />
          </div>

          <div className="flex flex-col space-y-4 p-4 bg-background rounded-lg border border-border">
            <span className="text-secondary font-bold">Theme Mode</span>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <button 
                onClick={() => handleThemeChange('light')}
                className={`p-4 rounded-lg border flex flex-col items-center justify-center transition-colors ${theme === 'light' ? 'bg-accent text-primary border-accent' : 'bg-surface border-border text-secondary hover:bg-surfaceHover'}`}
              >
                <Sun size={24} className="mb-2" />
                <span>Light</span>
              </button>
              <button 
                onClick={() => handleThemeChange('dark')}
                className={`p-4 rounded-lg border flex flex-col items-center justify-center transition-colors ${theme === 'dark' ? 'bg-accent text-primary border-accent' : 'bg-surface border-border text-secondary hover:bg-surfaceHover'}`}
              >
                <Moon size={24} className="mb-2" />
                <span>Dark</span>
              </button>
              <button 
                onClick={() => handleThemeChange('cyberpunk')}
                className={`p-4 rounded-lg border flex flex-col items-center justify-center transition-colors ${theme === 'cyberpunk' ? 'bg-accent text-primary border-accent' : 'bg-surface border-border text-secondary hover:bg-surfaceHover'}`}
              >
                <Zap size={24} className="mb-2" />
                <span>Cyberpunk</span>
              </button>
              <button 
                onClick={() => handleThemeChange('matrix')}
                className={`p-4 rounded-lg border flex flex-col items-center justify-center transition-colors ${theme === 'matrix' ? 'bg-accent text-primary border-accent' : 'bg-surface border-border text-secondary hover:bg-surfaceHover'}`}
              >
                <Terminal size={24} className="mb-2" />
                <span>Matrix</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-surface rounded-xl border border-border p-6 border-t-4 border-t-red-600">
        <h2 className="text-xl font-bold mb-4 text-red-500 flex items-center">
          <Trash2 className="mr-2" /> Danger Zone
        </h2>
        <p className="text-secondary mb-4">
          Resetting settings will revert all local configurations to their default values. This does not delete your VMs.
        </p>
        <button 
          onClick={handleReset}
          className="bg-red-900/50 hover:bg-red-900 text-red-200 px-4 py-2 rounded border border-red-800 flex items-center"
        >
          <RefreshCw size={16} className="mr-2" /> Reset Settings
        </button>
      </div>

      <Modal
        isOpen={resetConfirm}
        onClose={() => setResetConfirm(false)}
        title="Reset Settings"
        footer={
            <>
                <button onClick={() => setResetConfirm(false)} className="px-4 py-2 text-secondary hover:text-primary">Cancel</button>
                <button onClick={executeReset} className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded">Reset</button>
            </>
        }
      >
        <p className="text-secondary">Are you sure you want to reset all settings to default?</p>
      </Modal>
    </div>
  );
}

export default Settings;
