import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Loader2,
  Network,
  Play,
  Server,
  Sparkles,
} from 'lucide-react';
import Modal from './Modal';
import LiveEventTimeline from './LiveEventTimeline';
import { buildWebSocketUrl, getApiUrl } from '../lib/api';
import { useAuth } from '../context/AuthContext';

const API_URL = getApiUrl();
const SETTINGS_STORAGE_KEY = 'aiScenarioWorkflow.settings';

const PROVIDER_DEFAULTS = {
  ollama: {
    baseUrl: 'http://localhost:11434',
    model: 'qwen3:8b',
    label: 'Local Ollama',
    helper: 'Uses the local Ollama chat API at /api/chat.',
  },
  openai: {
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-4.1-mini',
    label: 'OpenAI',
    helper: 'Uses the OpenAI chat completions API.',
  },
  'openai-compatible': {
    baseUrl: 'http://localhost:1234/v1',
    model: 'local-model',
    label: 'OpenAI-Compatible',
    helper: 'Use this for Groq, LM Studio, vLLM, or another OpenAI-compatible endpoint.',
  },
};

function loadStoredSettings() {
  if (typeof window === 'undefined') {
    return {
      provider: 'ollama',
      model: PROVIDER_DEFAULTS.ollama.model,
      baseUrl: PROVIDER_DEFAULTS.ollama.baseUrl,
      apiKey: '',
      temperature: '0.2',
    };
  }

  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    const provider = parsed.provider && PROVIDER_DEFAULTS[parsed.provider] ? parsed.provider : 'ollama';
    return {
      provider,
      model: parsed.model || PROVIDER_DEFAULTS[provider].model,
      baseUrl: parsed.baseUrl || PROVIDER_DEFAULTS[provider].baseUrl,
      apiKey: '',
      temperature: parsed.temperature || '0.2',
    };
  } catch {
    return {
      provider: 'ollama',
      model: PROVIDER_DEFAULTS.ollama.model,
      baseUrl: PROVIDER_DEFAULTS.ollama.baseUrl,
      apiKey: '',
      temperature: '0.2',
    };
  }
}

function formatAsset(asset) {
  if (!asset || typeof asset !== 'object') {
    return null;
  }
  if (asset.type === 'package') {
    return `package: ${asset.value}`;
  }
  if (asset.type === 'command') {
    return `command: ${asset.value}`;
  }
  if (asset.type === 'ansible') {
    return `ansible: ${asset.playbook_name || 'playbook.yml'}`;
  }
  return null;
}

function formatAutomationStep(step) {
  if (!step || typeof step !== 'object') {
    return null;
  }

  if (step.type === 'wait') {
    return `wait ${step.delay_seconds || 0}s`;
  }
  if (step.type === 'send_text') {
    const text = typeof step.text === 'string' ? step.text.replace(/\n/g, '\\n') : '';
    return `send text: ${text || '(empty)'}`;
  }
  if (step.type === 'send_key') {
    return `send key: ${step.key || 'unknown'}`;
  }
  return null;
}

function formatRunbookStep(step) {
  if (!step || typeof step !== 'object') {
    return null;
  }

  const segments = [];
  if (step.actor) {
    segments.push(`actor ${step.actor}`);
  }
  if (step.target) {
    segments.push(`target ${step.target}`);
  }
  if (step.delay_seconds !== undefined && step.delay_seconds !== null) {
    segments.push(`delay ${step.delay_seconds}s`);
  }

  return segments.join(' · ');
}

function getRunbookPhaseSteps(phase) {
  if (!phase?.steps || typeof phase.steps !== 'object') {
    return [];
  }

  return Object.entries(phase.steps)
    .sort(([leftIndex], [rightIndex]) => Number(leftIndex) - Number(rightIndex))
    .map(([, step]) => step);
}

function summarizeDeployJob(job) {
  const result = job?.result || {};
  const jobKind = job?.progress?.job_kind || 'deploy';

  if (jobKind === 'runbook') {
    const runbookErrors = result?.runbook?.errors || [];
    const setupExecuted = (result?.runbook?.setup_results || []).filter((entry) => entry.status === 'completed').length;
    const simulationExecuted = (result?.runbook?.simulation_results || []).filter((entry) => entry.status === 'completed').length;

    let message = 'Scenario run finished.\n';
    message += `Setup steps completed: ${setupExecuted}\n`;
    message += `Simulation steps completed: ${simulationExecuted}`;

    if (runbookErrors.length > 0) {
      message += `\n\nWarnings: ${runbookErrors.length}`;
      runbookErrors.forEach((error) => {
        message += `\n- ${error.phase}: ${error.message}`;
      });
    }

    if (result?.detail) {
      message += `\n\nDetail:\n- ${result.detail}`;
    }

    return {
      message,
      type: runbookErrors.length > 0 ? 'error' : 'success',
    };
  }

  const entries = result?.results || [];
  const successes = entries.filter((entry) => entry.status === 'success');
  const failures = entries.filter((entry) => entry.status === 'error');
  const runbookErrors = result?.runbook?.errors || [];

  let message = 'Deployment finished.\n';
  message += `Successful VMs: ${successes.length}\n`;
  message += `Failed VMs: ${failures.length}`;

  if (failures.length > 0) {
    message += '\n\nErrors:\n';
    failures.forEach((entry) => {
      message += `- ${entry.node || entry.name || 'Unknown node'}: ${entry.message || entry.detail || 'error'}\n`;
    });
  }

  if (result?.runbook) {
    const setupExecuted = (result.runbook.setup_results || []).filter((entry) => entry.status === 'completed').length;
    const simulationExecuted = (result.runbook.simulation_results || []).filter((entry) => entry.status === 'completed').length;
    message += `\n\nRunbook execution:\n- Setup steps completed: ${setupExecuted}\n- Simulation steps completed: ${simulationExecuted}`;
    if (runbookErrors.length > 0) {
      message += `\n- Runbook warnings: ${runbookErrors.length}`;
      runbookErrors.forEach((error) => {
        message += `\n  - ${error.phase}: ${error.message}`;
      });
    }
  }

  if (result?.detail) {
    message += `\n\nDetail:\n- ${result.detail}`;
  }

  return {
    message,
    type: failures.length > 0 ? 'error' : 'success',
  };
}

export default function AIScenarios({ onOpenBuilder }) {
  const { token, user } = useAuth();
  const [settings, setSettings] = useState(() => loadStoredSettings());
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [deployingPreview, setDeployingPreview] = useState(false);
  const [runningScenario, setRunningScenario] = useState(false);
  const [result, setResult] = useState(null);
  const [deployJobId, setDeployJobId] = useState(null);
  const [deployJob, setDeployJob] = useState(null);
  const [lastDeploymentId, setLastDeploymentId] = useState(null);
  const [deployJobError, setDeployJobError] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [messageModal, setMessageModal] = useState({ isOpen: false, title: '', message: '', type: 'info' });
  const wsRef = useRef(null);
  const wsReconnectTimer = useRef(null);

  const topologyStorageKey = user ? `networkTopology:${user.id}` : 'networkTopology';
  const providerConfig = PROVIDER_DEFAULTS[settings.provider] || PROVIDER_DEFAULTS.ollama;
  const topology = result?.topology;
  const runbook = topology?.scenario?.runbook;
  const deployRunbook = deployJob?.progress?.runbook;
  const deploySetupSteps = getRunbookPhaseSteps(deployRunbook?.setup);
  const deploySimulationSteps = getRunbookPhaseSteps(deployRunbook?.simulation);
  const displayDeployStatus = (deployJob?.status || 'queued').replace(/_/g, ' ');
  const jobKind = deployJob?.progress?.job_kind || 'deploy';
  const runbookDeploymentId = deployJob?.progress?.deployment_id || lastDeploymentId;

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    window.localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({
        provider: settings.provider,
        model: settings.model,
        baseUrl: settings.baseUrl,
        temperature: settings.temperature,
      })
    );
  }, [settings.baseUrl, settings.model, settings.provider, settings.temperature]);

  useEffect(() => {
    if (!deployJobId) {
      return undefined;
    }

    let cancelled = false;
    let timeoutId;

    const poll = async () => {
      try {
        const response = await axios.get(`${API_URL}/topology/deploy-jobs/${deployJobId}`);
        if (cancelled) {
          return;
        }

        setDeployJob(response.data);
        setDeployJobError(null);
        const status = response.data?.status;
        if (status === 'completed' || status === 'failed') {
          if ((response.data?.progress?.job_kind || 'deploy') === 'deploy' && status === 'completed') {
            setLastDeploymentId(response.data?.job_id || null);
          }
          setDeployJobId(null);
          const summary = summarizeDeployJob(response.data);
          setMessageModal({
            isOpen: true,
            title: status === 'completed'
              ? ((response.data?.progress?.job_kind || 'deploy') === 'runbook' ? 'Scenario Run Finished' : 'Deployment Finished')
              : 'Job Failed',
            message: summary.message,
            type: summary.type,
          });
          return;
        }
        timeoutId = window.setTimeout(poll, 1000);
      } catch (error) {
        if (cancelled) {
          return;
        }
        const detail = error.response?.data?.detail || error.message || 'Failed to poll deployment job';
        setDeployJobError(detail);
        timeoutId = window.setTimeout(poll, 2000);
      }
    };

    poll();

    return () => {
      cancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [deployJobId]);

  useEffect(() => {
    if (!deployJobId || !token) {
      return undefined;
    }

    let cancelled = false;

    const connectWs = () => {
      if (cancelled) {
        return;
      }
      const ws = new WebSocket(buildWebSocketUrl(`/api/ws/deploy-jobs/${deployJobId}`, token));
      wsRef.current = ws;
      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          setLiveEvents((prev) => [payload, ...prev].slice(0, 100));
        } catch (error) {
          console.error('Invalid deploy-job websocket message', error);
        }
      };
      ws.onclose = () => {
        if (!cancelled) {
          wsReconnectTimer.current = window.setTimeout(connectWs, 3000);
        }
      };
    };

    connectWs();

    return () => {
      cancelled = true;
      if (wsReconnectTimer.current) {
        window.clearTimeout(wsReconnectTimer.current);
      }
      try {
        wsRef.current?.close();
      } catch {
        // Ignore close errors.
      }
      wsRef.current = null;
    };
  }, [deployJobId, token]);

  const updateSetting = (key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleProviderChange = (nextProvider) => {
    const previousDefaults = PROVIDER_DEFAULTS[settings.provider] || PROVIDER_DEFAULTS.ollama;
    const nextDefaults = PROVIDER_DEFAULTS[nextProvider] || PROVIDER_DEFAULTS.ollama;
    setSettings((prev) => ({
      ...prev,
      provider: nextProvider,
      baseUrl: prev.baseUrl === previousDefaults.baseUrl || !prev.baseUrl ? nextDefaults.baseUrl : prev.baseUrl,
      model: prev.model === previousDefaults.model || !prev.model ? nextDefaults.model : prev.model,
    }));
  };

  const buildWorkflowPayload = (autoDeploy) => ({
    prompt: prompt.trim(),
    auto_deploy: autoDeploy,
    provider: {
      provider: settings.provider,
      model: settings.model.trim(),
      base_url: settings.baseUrl.trim() || null,
      api_key: settings.apiKey.trim() || null,
      temperature: Number(settings.temperature || '0.2'),
    },
  });

  const runWorkflow = async (autoDeploy = false) => {
    if (!prompt.trim()) {
      setMessageModal({ isOpen: true, title: 'Missing Prompt', message: 'Describe the scenario you want the agent to build.', type: 'error' });
      return;
    }
    if (!settings.model.trim()) {
      setMessageModal({ isOpen: true, title: 'Missing Model', message: 'Choose a model before running the workflow.', type: 'error' });
      return;
    }

    setBusy(true);
    setDeployJob(null);
    setDeployJobId(null);
    setLastDeploymentId(null);
    setDeployJobError(null);
    setLiveEvents([]);

    try {
      const response = await axios.post(`${API_URL}/llm/scenario-workflows`, buildWorkflowPayload(autoDeploy));
      setResult(response.data);
      if (response.data?.deploy_job_id) {
        setDeployJobId(response.data.deploy_job_id);
      }
    } catch (error) {
      const detail = error.response?.data?.detail || error.message || 'Failed to run the AI scenario workflow';
      setMessageModal({ isOpen: true, title: 'Workflow Failed', message: detail, type: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const deployPreview = async () => {
    if (!topology) {
      return;
    }

    setDeployingPreview(true);
    setDeployJob(null);
    setDeployJobId(null);
    setLastDeploymentId(null);
    setDeployJobError(null);
    setLiveEvents([]);

    try {
      const response = await axios.post(`${API_URL}/topology/deploy-jobs`, topology);
      if (!response.data?.job_id) {
        throw new Error('The backend did not return a deployment job ID');
      }
      setDeployJobId(response.data.job_id);
    } catch (error) {
      const detail = error.response?.data?.detail || error.message || 'Failed to start deployment';
      setDeployJobError(detail);
      setMessageModal({ isOpen: true, title: 'Deployment Failed', message: detail, type: 'error' });
    } finally {
      setDeployingPreview(false);
    }
  };

  const runScenarioSimulation = async () => {
    if (!runbookDeploymentId || !runbook?.simulation_steps?.length) {
      return;
    }

    setRunningScenario(true);
    setDeployJob(null);
    setDeployJobId(null);
    setDeployJobError(null);
    setLiveEvents([]);

    try {
      const response = await axios.post(`${API_URL}/deployments/${runbookDeploymentId}/runbook-jobs`, {
        phases: ['simulation'],
        execution_mode: 'actor_parallel',
        agent_mode: 'prefer',
      });
      if (!response.data?.job_id) {
        throw new Error('The backend did not return a run job ID');
      }
      setDeployJobId(response.data.job_id);
    } catch (error) {
      const detail = error.response?.data?.detail || error.message || 'Failed to start the scenario run';
      setDeployJobError(detail);
      setMessageModal({ isOpen: true, title: 'Scenario Run Failed', message: detail, type: 'error' });
    } finally {
      setRunningScenario(false);
    }
  };

  const openInBuilder = async () => {
    if (!topology) {
      return;
    }

    const cachedTopology = { ...topology, viewport: null };
    window.localStorage.setItem(topologyStorageKey, JSON.stringify(cachedTopology));
    window.dispatchEvent(new CustomEvent('cyberranger:apply-topology', { detail: { topology: cachedTopology } }));

    try {
      await axios.post(`${API_URL}/topology/cache`, cachedTopology);
    } catch {
      setMessageModal({
        isOpen: true,
        title: 'Builder Cache Warning',
        message: 'The generated topology was saved locally, but the backend cache update failed. The builder will still load it in this browser session.',
        type: 'info',
      });
    }

    if (onOpenBuilder) {
      onOpenBuilder();
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)] gap-6">
        <div className="bg-surface border border-border rounded-2xl p-6 space-y-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-accent text-sm uppercase tracking-[0.2em]">
                <Sparkles size={16} /> Agentic Workflow
              </div>
              <h2 className="text-2xl font-bold text-primary mt-2">Generate and Deploy AI-Built Scenarios</h2>
              <p className="text-secondary mt-2 max-w-3xl">
                Describe the environment you want. The workflow plans the lab, synthesizes a topology in the existing builder schema, validates it, and can hand it straight to the deployment pipeline.
              </p>
            </div>
            <div className="rounded-xl border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-accent max-w-xs">
              {providerConfig.label}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="block">
              <span className="block text-sm font-medium text-secondary mb-2">Provider</span>
              <select
                value={settings.provider}
                onChange={(event) => handleProviderChange(event.target.value)}
                className="w-full bg-background border border-border rounded-xl px-3 py-3 text-primary"
              >
                {Object.entries(PROVIDER_DEFAULTS).map(([value, config]) => (
                  <option key={value} value={value}>{config.label}</option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="block text-sm font-medium text-secondary mb-2">Model</span>
              <input
                type="text"
                value={settings.model}
                onChange={(event) => updateSetting('model', event.target.value)}
                className="w-full bg-background border border-border rounded-xl px-3 py-3 text-primary"
                placeholder={providerConfig.model}
              />
            </label>

            <label className="block md:col-span-2">
              <span className="block text-sm font-medium text-secondary mb-2">Base URL</span>
              <input
                type="text"
                value={settings.baseUrl}
                onChange={(event) => updateSetting('baseUrl', event.target.value)}
                className="w-full bg-background border border-border rounded-xl px-3 py-3 text-primary"
                placeholder={providerConfig.baseUrl}
              />
            </label>

            {settings.provider !== 'ollama' && (
              <label className="block md:col-span-2">
                <span className="block text-sm font-medium text-secondary mb-2">API Key</span>
                <input
                  type="password"
                  value={settings.apiKey}
                  onChange={(event) => updateSetting('apiKey', event.target.value)}
                  className="w-full bg-background border border-border rounded-xl px-3 py-3 text-primary"
                  placeholder="sk-..."
                />
              </label>
            )}

            <label className="block md:max-w-[220px]">
              <span className="block text-sm font-medium text-secondary mb-2">Temperature</span>
              <input
                type="number"
                min="0"
                max="1"
                step="0.1"
                value={settings.temperature}
                onChange={(event) => updateSetting('temperature', event.target.value)}
                className="w-full bg-background border border-border rounded-xl px-3 py-3 text-primary"
              />
            </label>
          </div>

          <div>
            <div className="flex items-center justify-between gap-4 mb-2">
              <span className="text-sm font-medium text-secondary">Scenario Prompt</span>
              <span className="text-xs text-secondary">Mention host roles, topology intent, and any tooling that should be preinstalled.</span>
            </div>
            <textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={10}
              className="w-full bg-background border border-border rounded-2xl px-4 py-4 text-primary resize-y"
              placeholder="Example: Build a three-node phishing investigation lab with a mail gateway, a compromised Windows workstation, and an analyst box with network tools. Keep it easy to medium difficulty and include a simple isolated segment for the victim host."
            />
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => runWorkflow(false)}
              disabled={busy}
              className={`inline-flex items-center gap-2 px-4 py-3 rounded-xl transition-colors ${busy ? 'bg-surfaceHover text-secondary cursor-not-allowed' : 'bg-accent hover:bg-accentHover text-primary'}`}
            >
              {busy ? <Loader2 className="animate-spin" size={16} /> : <Sparkles size={16} />}
              Generate Preview
            </button>
            <button
              onClick={() => runWorkflow(true)}
              disabled={busy}
              className={`inline-flex items-center gap-2 px-4 py-3 rounded-xl transition-colors ${busy ? 'bg-surfaceHover text-secondary cursor-not-allowed' : 'bg-green-600 hover:bg-green-700 text-white'}`}
            >
              {busy ? <Loader2 className="animate-spin" size={16} /> : <Play size={16} />}
              Generate And Deploy
            </button>
          </div>
        </div>

        <div className="bg-surface border border-border rounded-2xl p-6 space-y-5">
          <div className="flex items-center gap-2 text-primary font-semibold">
            <Bot size={18} /> Connection Notes
          </div>
          <p className="text-secondary text-sm">{providerConfig.helper}</p>

          <div className="space-y-3 text-sm">
            <div className="rounded-xl border border-border bg-background/60 p-4">
              <div className="text-primary font-medium">Local Ollama</div>
              <div className="text-secondary mt-1">Use `http://localhost:11434` and a local model tag such as `qwen3:8b` or another model you already pulled.</div>
            </div>
            <div className="rounded-xl border border-border bg-background/60 p-4">
              <div className="text-primary font-medium">OpenAI-Compatible Providers</div>
              <div className="text-secondary mt-1">Point the base URL at the provider’s OpenAI-compatible API root, usually ending in `/v1`, and supply the provider-issued API key.</div>
            </div>
            <div className="rounded-xl border border-border bg-background/60 p-4">
              <div className="text-primary font-medium">What Gets Generated</div>
              <div className="text-secondary mt-1">The workflow returns the same topology schema used by the existing Topology Builder and deploy-jobs pipeline, so previews and deployments stay consistent.</div>
            </div>
          </div>
        </div>
      </div>

      {(deployJobId || deployJob) && (
        <div className="bg-surface border border-border rounded-2xl p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-primary font-semibold">{jobKind === 'runbook' ? 'Scenario Run Progress' : 'Deployment Progress'}</div>
              <div className="text-secondary text-sm mt-1">
                {deployJob?.message || (jobKind === 'runbook' ? 'Starting scenario run...' : 'Starting deployment...')}
                {deployJobId ? ` (job ${deployJobId.slice(0, 8)}...)` : ''}
              </div>
              {deployJobError && <div className="text-red-400 text-sm mt-2">{deployJobError}</div>}
            </div>
            <div className="text-right text-sm">
              <div className="text-secondary">Status</div>
              <div className="text-primary font-medium capitalize">{displayDeployStatus}</div>
            </div>
          </div>
          {Object.keys(deployJob?.progress?.nodes || {}).length > 0 && (
            <div className="mt-5 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {Object.entries(deployJob?.progress?.nodes || {}).map(([nodeId, nodeStatus]) => {
                const label = topology?.nodes?.find((node) => node.id === nodeId)?.label || nodeId;
                const automation = nodeStatus?.automation || null;
                return (
                  <div key={nodeId} className="rounded-xl border border-border bg-background/60 p-4 text-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-primary font-medium">{label}</div>
                        <div className="text-secondary mt-1">{nodeId}</div>
                      </div>
                      <div className="text-secondary capitalize">{nodeStatus?.status || 'queued'}</div>
                    </div>
                    {nodeStatus?.message && <div className="text-secondary mt-3">{nodeStatus.message}</div>}
                    {automation?.status && (
                      <div className="mt-3 rounded-lg border border-border bg-surface px-3 py-2 text-secondary">
                        <div className="text-primary text-xs uppercase tracking-[0.2em]">Automation</div>
                        <div className="mt-1 capitalize">{automation.status}</div>
                        {(automation.step || automation.step === 0) && (
                          <div className="mt-1">Step {automation.step}{automation.step_type ? ` · ${automation.step_type}` : ''}</div>
                        )}
                        {automation.message && <div className="mt-1">{automation.message}</div>}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {deployRunbook && (
            <div className="mt-5 border-t border-border pt-5 space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-primary font-semibold">Runbook Execution</div>
                  <div className="text-secondary text-sm mt-1">
                    {deployRunbook.current_phase ? `Currently executing ${deployRunbook.current_phase}.` : 'Waiting for the next runbook phase.'}
                  </div>
                </div>
                <div className="text-secondary text-sm capitalize">{deployRunbook.status || 'pending'}</div>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                {[
                  { key: 'setup', label: 'Setup Phase', steps: deploySetupSteps, status: deployRunbook?.setup?.status },
                  { key: 'simulation', label: 'Simulation Phase', steps: deploySimulationSteps, status: deployRunbook?.simulation?.status },
                ].map((phase) => (
                  <div key={phase.key} className="rounded-xl border border-border bg-background/60 p-4 space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-primary font-medium">{phase.label}</div>
                      <div className="text-secondary text-sm capitalize">{phase.status || 'pending'}</div>
                    </div>

                    {phase.steps.length > 0 ? (
                      <div className="space-y-3">
                        {phase.steps.map((step, index) => {
                          const summary = formatRunbookStep(step);
                          const automationCount = step?.automation?.steps?.length || 0;
                          return (
                            <div key={`${phase.key}-${step.title}-${index}`} className="rounded-xl border border-border bg-surface px-4 py-3 text-sm">
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <div className="text-primary font-medium">{step.title}</div>
                                  {summary && <div className="text-secondary text-xs uppercase tracking-[0.18em] mt-2">{summary}</div>}
                                </div>
                                <div className="text-secondary capitalize">{step.status || 'pending'}</div>
                              </div>
                              <div className="text-secondary mt-2">{step.action}</div>
                              {automationCount > 0 && <div className="text-secondary mt-2">Console automation: {automationCount} steps</div>}
                              {(step.automation_step || step.automation_step === 0) && (
                                <div className="text-secondary mt-2">
                                  Automation step {step.automation_step}
                                  {step.automation_step_type ? ` · ${step.automation_step_type}` : ''}
                                </div>
                              )}
                              {step.message && <div className="text-secondary mt-2">{step.message}</div>}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-secondary text-sm">No {phase.key} steps were generated.</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <LiveEventTimeline
            title="Live Events"
            events={liveEvents}
            emptyMessage={deployJobId ? 'Connected. Waiting for deploy and runbook events.' : 'Start a deployment or scenario run to stream live events.'}
          />
        </div>
      )}

      {result && topology && (
        <div className="space-y-6">
          <div className="bg-surface border border-border rounded-2xl p-6 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="text-sm uppercase tracking-[0.2em] text-accent">Generated Scenario</div>
                <h3 className="text-2xl font-bold text-primary mt-2">{topology.scenario?.name || 'Generated Topology'}</h3>
                <p className="text-secondary mt-2 max-w-3xl">{result.summary}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={openInBuilder}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-surfaceHover hover:bg-background text-primary"
                >
                  <Network size={16} /> Open In Builder
                </button>
                <button
                  onClick={deployPreview}
                  disabled={deployingPreview || Boolean(deployJobId)}
                  className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl transition-colors ${deployingPreview || deployJobId ? 'bg-surfaceHover text-secondary cursor-not-allowed' : 'bg-green-600 hover:bg-green-700 text-white'}`}
                >
                  {deployingPreview ? <Loader2 className="animate-spin" size={16} /> : <Play size={16} />}
                  Deploy Preview
                </button>
                <button
                  onClick={runScenarioSimulation}
                  disabled={runningScenario || Boolean(deployJobId) || !runbookDeploymentId || !runbook?.simulation_steps?.length}
                  className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl transition-colors ${runningScenario || deployJobId || !runbookDeploymentId || !runbook?.simulation_steps?.length ? 'bg-surfaceHover text-secondary cursor-not-allowed' : 'bg-amber-600 hover:bg-amber-700 text-white'}`}
                >
                  {runningScenario ? <Loader2 className="animate-spin" size={16} /> : <Play size={16} />}
                  Run Simulation
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="rounded-xl border border-border bg-background/60 p-4">
                <div className="text-secondary text-sm">Team</div>
                <div className="text-primary font-semibold mt-2">{topology.scenario?.team || 'blue'}</div>
              </div>
              <div className="rounded-xl border border-border bg-background/60 p-4">
                <div className="text-secondary text-sm">Difficulty</div>
                <div className="text-primary font-semibold mt-2">{topology.scenario?.difficulty || 'medium'}</div>
              </div>
              <div className="rounded-xl border border-border bg-background/60 p-4">
                <div className="text-secondary text-sm">Nodes</div>
                <div className="text-primary font-semibold mt-2">{topology.nodes.length}</div>
              </div>
              <div className="rounded-xl border border-border bg-background/60 p-4">
                <div className="text-secondary text-sm">Links</div>
                <div className="text-primary font-semibold mt-2">{topology.edges.length}</div>
              </div>
            </div>

            <div>
              <div className="text-primary font-semibold">Objective</div>
              <p className="text-secondary mt-2">{topology.scenario?.objective}</p>
            </div>
          </div>

          {runbook && (
            <div className="bg-surface border border-border rounded-2xl p-6 space-y-5">
              <div className="flex items-center gap-2 text-primary font-semibold">
                <Bot size={18} /> Execution Plan
              </div>

              {runbook.provisioning_strategy && (
                <div className="rounded-xl border border-border bg-background/60 p-4">
                  <div className="text-secondary text-sm">Provisioning Strategy</div>
                  <div className="text-primary mt-2">{runbook.provisioning_strategy}</div>
                </div>
              )}

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                <div className="space-y-5">
                  <div>
                    <div className="text-primary font-medium">Setup Order</div>
                    {runbook.setup_order?.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {runbook.setup_order.map((nodeId) => {
                          const label = topology.nodes.find((node) => node.id === nodeId)?.label || nodeId;
                          return (
                            <span key={nodeId} className="inline-flex items-center rounded-full border border-border bg-background/60 px-3 py-1 text-sm text-secondary">
                              {label}
                            </span>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="mt-2 text-sm text-secondary">No explicit setup order was generated.</div>
                    )}
                  </div>

                  <div>
                    <div className="text-primary font-medium">Setup Steps</div>
                    {runbook.setup_steps?.length > 0 ? (
                      <div className="mt-3 space-y-3">
                        {runbook.setup_steps.map((step, index) => {
                          const summary = formatRunbookStep(step);
                          return (
                            <div key={`${step.title}-${index}`} className="rounded-xl border border-border bg-background/60 p-4">
                              <div className="text-primary font-medium">{step.title}</div>
                              {summary && <div className="text-secondary text-xs uppercase tracking-[0.18em] mt-2">{summary}</div>}
                              <div className="text-secondary text-sm mt-2">{step.action}</div>
                              {step.command && <div className="text-secondary text-sm mt-2">SSH command: {step.command}</div>}
                              {step.automation?.steps?.length > 0 && <div className="text-secondary text-sm mt-2">Console automation: {step.automation.steps.length} steps</div>}
                              {step.expected_outcome && <div className="text-secondary text-sm mt-2">Expected: {step.expected_outcome}</div>}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="mt-2 text-sm text-secondary">No setup steps were generated.</div>
                    )}
                  </div>

                  <div>
                    <div className="text-primary font-medium">Success Criteria</div>
                    {runbook.success_criteria?.length > 0 ? (
                      <div className="mt-3 space-y-2">
                        {runbook.success_criteria.map((criterion, index) => (
                          <div key={`${criterion}-${index}`} className="rounded-xl border border-border bg-background/60 px-4 py-3 text-sm text-secondary">
                            {criterion}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="mt-2 text-sm text-secondary">No success criteria were generated.</div>
                    )}
                  </div>
                </div>

                <div className="space-y-5">
                  <div>
                    <div className="text-primary font-medium">Simulation Steps</div>
                    {runbook.simulation_steps?.length > 0 ? (
                      <div className="mt-3 space-y-3">
                        {runbook.simulation_steps.map((step, index) => {
                          const summary = formatRunbookStep(step);
                          return (
                            <div key={`${step.title}-${index}`} className="rounded-xl border border-border bg-background/60 p-4">
                              <div className="text-primary font-medium">{step.title}</div>
                              {summary && <div className="text-secondary text-xs uppercase tracking-[0.18em] mt-2">{summary}</div>}
                              <div className="text-secondary text-sm mt-2">{step.action}</div>
                              {step.command && <div className="text-secondary text-sm mt-2">SSH command: {step.command}</div>}
                              {step.automation?.steps?.length > 0 && <div className="text-secondary text-sm mt-2">Console automation: {step.automation.steps.length} steps</div>}
                              {step.expected_outcome && <div className="text-secondary text-sm mt-2">Expected: {step.expected_outcome}</div>}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="mt-2 text-sm text-secondary">No simulation steps were generated.</div>
                    )}
                  </div>

                  <div>
                    <div className="text-primary font-medium">Visualization Targets</div>
                    {runbook.visualizations?.length > 0 ? (
                      <div className="mt-3 space-y-3">
                        {runbook.visualizations.map((visualization, index) => {
                          const label = visualization.node_id
                            ? topology.nodes.find((node) => node.id === visualization.node_id)?.label || visualization.node_id
                            : null;
                          return (
                            <div key={`${visualization.title}-${index}`} className="rounded-xl border border-border bg-background/60 p-4">
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <div className="text-primary font-medium">{visualization.title}</div>
                                  <div className="text-secondary text-sm mt-1 capitalize">{visualization.kind || 'dashboard'}</div>
                                </div>
                                {label && <div className="text-secondary text-sm">{label}</div>}
                              </div>
                              {visualization.description && <div className="text-secondary text-sm mt-2">{visualization.description}</div>}
                              {visualization.url_hint && <div className="text-secondary text-sm mt-2">{visualization.url_hint}</div>}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="mt-2 text-sm text-secondary">No visualization targets were generated.</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)] gap-6">
            <div className="bg-surface border border-border rounded-2xl p-6 space-y-4">
              <div className="flex items-center gap-2 text-primary font-semibold">
                <Server size={18} /> Nodes
              </div>
              <div className="space-y-4">
                {topology.nodes.map((node) => (
                  <div key={node.id} className="rounded-2xl border border-border bg-background/60 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="text-primary font-semibold">{node.label}</div>
                        <div className="text-secondary text-sm mt-1">{node.config.image}</div>
                      </div>
                      <div className="text-right text-sm text-secondary">
                        <div>{node.config.cpu} vCPU</div>
                        <div>{node.config.ram} MB RAM</div>
                      </div>
                    </div>
                    {node.config.assets?.length > 0 && (
                      <div className="mt-4">
                        <div className="text-xs uppercase tracking-[0.2em] text-secondary">Bootstrap Assets</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {node.config.assets.slice(0, 4).map((asset, index) => {
                            const label = formatAsset(asset);
                            if (!label) {
                              return null;
                            }
                            return (
                              <span key={`${node.id}-asset-${index}`} className="inline-flex items-center rounded-full border border-border px-3 py-1 text-xs text-secondary bg-surface">
                                {label}
                              </span>
                            );
                          })}
                          {node.config.assets.length > 4 && (
                            <span className="inline-flex items-center rounded-full border border-border px-3 py-1 text-xs text-secondary bg-surface">
                              +{node.config.assets.length - 4} more
                            </span>
                          )}
                        </div>
                      </div>
                    )}

                    {node.config.automation?.steps?.length > 0 && (
                      <div className="mt-4">
                        <div className="text-xs uppercase tracking-[0.2em] text-secondary">Console Automation</div>
                        <div className="mt-2 space-y-2">
                          {node.config.automation.steps.slice(0, 4).map((step, index) => {
                            const label = formatAutomationStep(step);
                            if (!label) {
                              return null;
                            }
                            return (
                              <div key={`${node.id}-automation-${index}`} className="rounded-xl border border-border bg-surface px-3 py-2 text-sm text-secondary">
                                {label}
                              </div>
                            );
                          })}
                          {node.config.automation.steps.length > 4 && (
                            <div className="text-xs text-secondary">+{node.config.automation.steps.length - 4} more automation steps</div>
                          )}
                        </div>
                      </div>
                    )}

                    {!node.config.assets?.length && !node.config.automation?.steps?.length && (
                      <div className="mt-4 text-sm text-secondary">No bootstrap assets or console automation were generated for this node.</div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-6">
              <div className="bg-surface border border-border rounded-2xl p-6 space-y-4">
                <div className="flex items-center gap-2 text-primary font-semibold">
                  <Network size={18} /> Links
                </div>
                {topology.edges.length > 0 ? (
                  <div className="space-y-3">
                    {topology.edges.map((edge) => (
                      <div key={edge.id || `${edge.source}-${edge.target}`} className="rounded-xl border border-border bg-background/60 p-4 text-sm">
                        <div className="text-primary font-medium">{edge.source}{' -> '}{edge.target}</div>
                        <div className="text-secondary mt-1">
                          {(edge.config?.segment && `Segment ${edge.config.segment}`) || 'Shared segment'}
                          {edge.config?.mode ? ` · ${edge.config.mode}` : ''}
                          {edge.config?.vlan_id !== undefined && edge.config?.vlan_id !== null ? ` · VLAN ${edge.config.vlan_id}` : ''}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-secondary text-sm">No explicit links were generated for this topology.</div>
                )}
              </div>

              <div className="bg-surface border border-border rounded-2xl p-6 space-y-4">
                <div className="flex items-center gap-2 text-primary font-semibold">
                  <CheckCircle2 size={18} /> Workflow Trace
                </div>
                <div className="space-y-3">
                  {result.workflow.map((step) => (
                    <div key={step.stage} className="rounded-xl border border-border bg-background/60 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-primary font-medium capitalize">{step.stage}</div>
                        <div className="text-xs uppercase tracking-[0.2em] text-secondary">{step.duration_ms} ms</div>
                      </div>
                      <div className="text-secondary text-sm mt-2">{step.message}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="bg-surface border border-border rounded-2xl p-6 space-y-4">
                <div className="flex items-center gap-2 text-primary font-semibold">
                  <AlertTriangle size={18} /> Warnings
                </div>
                {result.warnings?.length > 0 ? (
                  <div className="space-y-3">
                    {result.warnings.map((warning, index) => (
                      <div key={`${warning}-${index}`} className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
                        {warning}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-secondary text-sm">The workflow did not report any validation warnings.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <Modal
        isOpen={messageModal.isOpen}
        onClose={() => setMessageModal((prev) => ({ ...prev, isOpen: false }))}
        title={messageModal.title}
        footer={<button onClick={() => setMessageModal((prev) => ({ ...prev, isOpen: false }))} className="px-4 py-2 bg-surface hover:bg-surfaceHover text-primary rounded">Close</button>}
      >
        <div className={`text-sm whitespace-pre-wrap ${messageModal.type === 'error' ? 'text-red-400' : messageModal.type === 'success' ? 'text-green-400' : 'text-secondary'}`}>
          {messageModal.message}
        </div>
      </Modal>
    </div>
  );
}