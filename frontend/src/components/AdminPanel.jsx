import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { Activity, BarChart3, RefreshCw, Save, Shield, UserPlus, Users } from 'lucide-react';
import { getApiUrl } from '../lib/api';

const API_URL = getApiUrl();

function formatTimestamp(value) {
  if (!value) {
    return 'Never';
  }
  return new Date(value * 1000).toLocaleString();
}

function formatPercent(value) {
  return `${Math.round((Number(value || 0) || 0) * 100)}%`;
}

function AdminPanel() {
  const [dashboard, setDashboard] = useState(null);
  const [users, setUsers] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [createForm, setCreateForm] = useState({ username: '', full_name: '', password: '', role: 'user' });
  const [loading, setLoading] = useState(true);
  const [savingUserId, setSavingUserId] = useState('');
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState({ type: '', text: '' });

  const fetchData = async () => {
    setLoading(true);
    try {
      const [dashboardRes, usersRes] = await Promise.all([
        axios.get(`${API_URL}/admin/dashboard`),
        axios.get(`${API_URL}/admin/users`),
      ]);
      setDashboard(dashboardRes.data);
      setUsers(usersRes.data || []);
      setDrafts(
        Object.fromEntries(
          (usersRes.data || []).map((user) => [
            user.id,
            {
              full_name: user.full_name || '',
              role: user.role || 'user',
              is_active: user.is_active !== false,
              password: '',
            },
          ])
        )
      );
      setMessage({ type: '', text: '' });
    } catch (error) {
      setMessage({ type: 'error', text: error.response?.data?.detail || error.message || 'Failed to load admin data' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const totals = dashboard?.totals || {};
  const userSummaries = useMemo(() => dashboard?.users || [], [dashboard]);
  const recentRuns = useMemo(() => dashboard?.recent_run_evaluations || [], [dashboard]);

  const updateDraft = (userId, field, value) => {
    setDrafts((current) => ({
      ...current,
      [userId]: {
        ...(current[userId] || {}),
        [field]: value,
      },
    }));
  };

  const handleCreateUser = async (event) => {
    event.preventDefault();
    setCreating(true);
    try {
      await axios.post(`${API_URL}/admin/users`, createForm);
      setCreateForm({ username: '', full_name: '', password: '', role: 'user' });
      setMessage({ type: 'success', text: 'User created.' });
      await fetchData();
    } catch (error) {
      setMessage({ type: 'error', text: error.response?.data?.detail || error.message || 'Failed to create user' });
    } finally {
      setCreating(false);
    }
  };

  const handleSaveUser = async (userId) => {
    const draft = drafts[userId] || {};
    setSavingUserId(userId);
    try {
      await axios.patch(`${API_URL}/admin/users/${userId}`, {
        full_name: draft.full_name,
        role: draft.role,
        is_active: draft.is_active,
        password: draft.password?.trim() ? draft.password : undefined,
      });
      setMessage({ type: 'success', text: 'User updated.' });
      await fetchData();
    } catch (error) {
      setMessage({ type: 'error', text: error.response?.data?.detail || error.message || 'Failed to update user' });
    } finally {
      setSavingUserId('');
    }
  };

  if (loading && !dashboard) {
    return <div className="text-secondary">Loading admin dashboard...</div>;
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs uppercase tracking-[0.25em] text-secondary">Administration</div>
          <h2 className="text-2xl font-bold text-primary mt-2">User Management And Training Oversight</h2>
        </div>
        <button onClick={fetchData} className="px-4 py-2 rounded-lg bg-surfaceHover hover:bg-surface text-primary flex items-center gap-2">
          <RefreshCw size={16} /> Refresh
        </button>
      </div>

      {message.text && (
        <div className={`rounded-2xl border px-4 py-3 text-sm ${message.type === 'error' ? 'border-red-800 bg-red-950/40 text-red-300' : 'border-emerald-800 bg-emerald-950/30 text-emerald-300'}`}>
          {message.text}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="rounded-2xl border border-border bg-surface p-5">
          <div className="flex items-center gap-2 text-secondary text-sm"><Users size={16} /> Users</div>
          <div className="text-3xl font-black mt-3">{totals.users || 0}</div>
          <div className="text-sm text-secondary mt-1">{totals.active_users || 0} active</div>
        </div>
        <div className="rounded-2xl border border-border bg-surface p-5">
          <div className="flex items-center gap-2 text-secondary text-sm"><Shield size={16} /> Admins</div>
          <div className="text-3xl font-black mt-3">{totals.admins || 0}</div>
          <div className="text-sm text-secondary mt-1">Privileged accounts</div>
        </div>
        <div className="rounded-2xl border border-border bg-surface p-5">
          <div className="flex items-center gap-2 text-secondary text-sm"><Activity size={16} /> Training Runs</div>
          <div className="text-3xl font-black mt-3">{totals.training_runs || 0}</div>
          <div className="text-sm text-secondary mt-1">{totals.running_training_runs || 0} currently running</div>
        </div>
        <div className="rounded-2xl border border-border bg-surface p-5">
          <div className="flex items-center gap-2 text-secondary text-sm"><BarChart3 size={16} /> Resources</div>
          <div className="text-3xl font-black mt-3">{totals.tracked_vms || 0}</div>
          <div className="text-sm text-secondary mt-1">{totals.deployments || 0} active deployments</div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr] gap-6">
        <div className="rounded-3xl border border-border bg-surface p-6 space-y-5">
          <div className="flex items-center gap-2 text-primary font-bold text-lg"><UserPlus size={18} /> Create User</div>
          <form onSubmit={handleCreateUser} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <input
              value={createForm.username}
              onChange={(event) => setCreateForm((current) => ({ ...current, username: event.target.value }))}
              className="rounded-xl border border-border bg-background px-4 py-3 text-primary"
              placeholder="Username"
              required
            />
            <input
              value={createForm.full_name}
              onChange={(event) => setCreateForm((current) => ({ ...current, full_name: event.target.value }))}
              className="rounded-xl border border-border bg-background px-4 py-3 text-primary"
              placeholder="Full name"
            />
            <input
              type="password"
              value={createForm.password}
              onChange={(event) => setCreateForm((current) => ({ ...current, password: event.target.value }))}
              className="rounded-xl border border-border bg-background px-4 py-3 text-primary"
              placeholder="Temporary password"
              required
            />
            <select
              value={createForm.role}
              onChange={(event) => setCreateForm((current) => ({ ...current, role: event.target.value }))}
              className="rounded-xl border border-border bg-background px-4 py-3 text-primary"
            >
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
            <button
              type="submit"
              disabled={creating}
              className="md:col-span-2 rounded-xl bg-accent hover:bg-accentHover disabled:opacity-60 text-white px-4 py-3 font-semibold"
            >
              {creating ? 'Creating...' : 'Create User'}
            </button>
          </form>
        </div>

        <div className="rounded-3xl border border-border bg-surface p-6">
          <div className="text-primary font-bold text-lg mb-4">Per-user activity</div>
          <div className="space-y-3 max-h-[28rem] overflow-auto pr-1">
            {userSummaries.map((summary) => (
              <div key={summary.user.id} className="rounded-2xl border border-border bg-background p-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="font-semibold text-primary">{summary.user.full_name || summary.user.username}</div>
                    <div className="text-xs uppercase tracking-[0.2em] text-secondary mt-1">{summary.user.role} · {summary.user.is_active ? 'Active' : 'Disabled'}</div>
                  </div>
                  <div className="text-right text-xs text-secondary">Last activity<br />{formatTimestamp(summary.last_activity_at)}</div>
                </div>
                <div className="grid grid-cols-2 gap-3 mt-4 text-sm">
                  <div className="rounded-xl border border-border p-3">Runs: <span className="font-semibold text-primary">{summary.training.total_runs}</span></div>
                  <div className="rounded-xl border border-border p-3">Running: <span className="font-semibold text-primary">{summary.training.running_runs}</span></div>
                  <div className="rounded-xl border border-border p-3">Avg score: <span className="font-semibold text-primary">{Math.round(summary.training.average_score || 0)}</span></div>
                  <div className="rounded-xl border border-border p-3">Completion: <span className="font-semibold text-primary">{formatPercent(summary.training.average_completion_ratio)}</span></div>
                  <div className="rounded-xl border border-border p-3">Deployments: <span className="font-semibold text-primary">{summary.resources.deployment_count}</span></div>
                  <div className="rounded-xl border border-border p-3">Tracked VMs: <span className="font-semibold text-primary">{summary.resources.vm_count}</span></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-3xl border border-border bg-surface overflow-hidden">
        <div className="p-6 border-b border-border text-primary font-bold text-lg">Manage Users</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left">
            <thead className="bg-background text-secondary text-sm">
              <tr>
                <th className="px-4 py-3">Username</th>
                <th className="px-4 py-3">Full name</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Active</th>
                <th className="px-4 py-3">Reset password</th>
                <th className="px-4 py-3">Last login</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {users.map((user) => {
                const draft = drafts[user.id] || {};
                return (
                  <tr key={user.id} className="align-top">
                    <td className="px-4 py-3 font-medium text-primary">{user.username}</td>
                    <td className="px-4 py-3">
                      <input
                        value={draft.full_name || ''}
                        onChange={(event) => updateDraft(user.id, 'full_name', event.target.value)}
                        className="w-full rounded-xl border border-border bg-background px-3 py-2 text-primary"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={draft.role || 'user'}
                        onChange={(event) => updateDraft(user.id, 'role', event.target.value)}
                        className="w-full rounded-xl border border-border bg-background px-3 py-2 text-primary"
                      >
                        <option value="user">User</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td className="px-4 py-3">
                      <label className="inline-flex items-center gap-2 text-sm text-primary">
                        <input
                          type="checkbox"
                          checked={draft.is_active !== false}
                          onChange={(event) => updateDraft(user.id, 'is_active', event.target.checked)}
                          className="h-4 w-4 accent-accent"
                        />
                        Enabled
                      </label>
                    </td>
                    <td className="px-4 py-3">
                      <input
                        type="password"
                        value={draft.password || ''}
                        onChange={(event) => updateDraft(user.id, 'password', event.target.value)}
                        className="w-full rounded-xl border border-border bg-background px-3 py-2 text-primary"
                        placeholder="Leave blank"
                      />
                    </td>
                    <td className="px-4 py-3 text-secondary text-sm">{formatTimestamp(user.last_login_at)}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => handleSaveUser(user.id)}
                        disabled={savingUserId === user.id}
                        className="rounded-xl bg-surfaceHover hover:bg-surface text-primary px-3 py-2 flex items-center gap-2 disabled:opacity-60"
                      >
                        <Save size={14} /> {savingUserId === user.id ? 'Saving...' : 'Save'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-3xl border border-border bg-surface overflow-hidden">
        <div className="p-6 border-b border-border text-primary font-bold text-lg">Recent Training Evaluations</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left">
            <thead className="bg-background text-secondary text-sm">
              <tr>
                <th className="px-4 py-3">Training</th>
                <th className="px-4 py-3">Participants</th>
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Completion</th>
                <th className="px-4 py-3">Attempts</th>
                <th className="px-4 py-3">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {recentRuns.map((evaluation) => (
                <tr key={evaluation.run_id}>
                  <td className="px-4 py-3 text-primary font-medium">{evaluation.training_title || evaluation.definition_id}</td>
                  <td className="px-4 py-3 text-secondary">{(evaluation.participants || []).join(', ') || 'Unassigned'}</td>
                  <td className="px-4 py-3 text-secondary">{evaluation.state}</td>
                  <td className="px-4 py-3 text-primary">{evaluation.total_score || 0}</td>
                  <td className="px-4 py-3 text-primary">{formatPercent(evaluation.completion_ratio)}</td>
                  <td className="px-4 py-3 text-secondary">{evaluation.total_attempts || 0}</td>
                  <td className="px-4 py-3 text-secondary">{formatTimestamp(evaluation.created_at)}</td>
                </tr>
              ))}
              {recentRuns.length === 0 && (
                <tr>
                  <td colSpan="7" className="px-4 py-8 text-center text-secondary">No training runs have been recorded yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default AdminPanel;