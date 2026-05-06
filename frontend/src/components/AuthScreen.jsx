import React, { useMemo, useState } from 'react';
import { LogIn, Shield, UserPlus } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

function AuthScreen() {
  const { allowSelfRegistration, login, register } = useAuth();
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ username: '', password: '', fullName: '' });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const title = useMemo(() => (mode === 'login' ? 'Sign In' : 'Create Account'), [mode]);

  const updateField = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      if (mode === 'login') {
        await login({ username: form.username, password: form.password });
      } else {
        await register({ username: form.username, password: form.password, fullName: form.fullName });
      }
    } catch (requestError) {
      setError(requestError.response?.data?.detail || requestError.message || 'Authentication failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-primary flex items-center justify-center p-6">
      <div className="w-full max-w-5xl grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] bg-surface border border-border rounded-3xl overflow-hidden shadow-2xl">
        <div className="relative p-10 lg:p-12 border-b lg:border-b-0 lg:border-r border-border bg-gradient-to-br from-surface via-background to-surface">
          <div className="absolute inset-0 opacity-30 pointer-events-none" style={{ backgroundImage: 'radial-gradient(circle at top left, rgba(37,99,235,0.3), transparent 35%), radial-gradient(circle at bottom right, rgba(16,185,129,0.18), transparent 30%)' }} />
          <div className="relative space-y-8">
            <div className="flex items-center gap-4">
              <img src="/cyberranger.jpg" alt="CyberRanger logo" className="h-16 w-16 rounded-2xl border border-border object-cover" />
              <div>
                <div className="text-sm uppercase tracking-[0.35em] text-secondary">Cyber Range</div>
                <h1 className="text-4xl font-black tracking-tight">CyberRanger</h1>
              </div>
            </div>

            <div className="space-y-4 max-w-xl">
              <h2 className="text-3xl font-bold leading-tight">Multi-user training labs with isolated VMs, topologies, and progress tracking.</h2>
              <p className="text-secondary text-base leading-7">
                Sign in to access your assigned environments. Admin accounts can manage users, review training metrics,
                and monitor active exercises from a single control panel.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="rounded-2xl border border-border bg-background/60 p-4">
                <div className="text-xs uppercase tracking-[0.25em] text-secondary mb-2">Isolation</div>
                <div className="text-sm text-primary">Each user sees only their own deployments and training environments.</div>
              </div>
              <div className="rounded-2xl border border-border bg-background/60 p-4">
                <div className="text-xs uppercase tracking-[0.25em] text-secondary mb-2">Metrics</div>
                <div className="text-sm text-primary">Training evaluations and progress are available for admins in one dashboard.</div>
              </div>
              <div className="rounded-2xl border border-border bg-background/60 p-4">
                <div className="text-xs uppercase tracking-[0.25em] text-secondary mb-2">Control</div>
                <div className="text-sm text-primary">Admins can add users, adjust roles, and deactivate access without editing files.</div>
              </div>
            </div>
          </div>
        </div>

        <div className="p-8 lg:p-12 bg-surface">
          <div className="max-w-md mx-auto space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-secondary uppercase tracking-[0.25em]">Access</div>
                <h3 className="text-2xl font-bold mt-2">{title}</h3>
              </div>
              <div className="rounded-full bg-background border border-border p-3 text-accent">
                {mode === 'login' ? <Shield size={22} /> : <UserPlus size={22} />}
              </div>
            </div>

            <div className="flex gap-2 rounded-full bg-background border border-border p-1">
              <button
                type="button"
                onClick={() => setMode('login')}
                className={`flex-1 rounded-full px-4 py-2 text-sm font-medium transition-colors ${mode === 'login' ? 'bg-accent text-white' : 'text-secondary hover:text-primary'}`}
              >
                Login
              </button>
              {allowSelfRegistration && (
                <button
                  type="button"
                  onClick={() => setMode('register')}
                  className={`flex-1 rounded-full px-4 py-2 text-sm font-medium transition-colors ${mode === 'register' ? 'bg-accent text-white' : 'text-secondary hover:text-primary'}`}
                >
                  Register
                </button>
              )}
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              {mode === 'register' && (
                <div>
                  <label className="block text-sm text-secondary mb-2">Full name</label>
                  <input
                    value={form.fullName}
                    onChange={(event) => updateField('fullName', event.target.value)}
                    className="w-full rounded-2xl border border-border bg-background px-4 py-3 text-primary outline-none focus:border-accent"
                    placeholder="Jane Doe"
                  />
                </div>
              )}

              <div>
                <label className="block text-sm text-secondary mb-2">Username</label>
                <input
                  value={form.username}
                  onChange={(event) => updateField('username', event.target.value)}
                  className="w-full rounded-2xl border border-border bg-background px-4 py-3 text-primary outline-none focus:border-accent"
                  placeholder="analyst01"
                  required
                />
              </div>

              <div>
                <label className="block text-sm text-secondary mb-2">Password</label>
                <input
                  type="password"
                  value={form.password}
                  onChange={(event) => updateField('password', event.target.value)}
                  className="w-full rounded-2xl border border-border bg-background px-4 py-3 text-primary outline-none focus:border-accent"
                  placeholder="At least 8 characters"
                  required
                />
              </div>

              {error && <div className="rounded-2xl border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</div>}

              <button
                type="submit"
                disabled={submitting}
                className="w-full rounded-2xl bg-accent hover:bg-accentHover disabled:opacity-60 disabled:cursor-not-allowed text-white px-4 py-3 font-semibold flex items-center justify-center gap-2 transition-colors"
              >
                {mode === 'login' ? <LogIn size={18} /> : <UserPlus size={18} />}
                {submitting ? 'Please wait...' : title}
              </button>
            </form>

            {!allowSelfRegistration && (
              <div className="rounded-2xl border border-border bg-background/70 px-4 py-3 text-sm text-secondary">
                Self-registration is disabled. Ask an administrator to create your account.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default AuthScreen;