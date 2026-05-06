import axios from 'axios';

export const getApiUrl = () => {
  const envUrl = (import.meta?.env?.VITE_API_URL || '').trim();
  if (envUrl) return envUrl;
  const hostname = window.location.hostname || 'localhost';
  return `http://${hostname}:8001/api`;
};

export const AUTH_STORAGE_KEY = 'cyberranger.auth';

export const getStoredAuth = () => {
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};

export const saveStoredAuth = (auth) => {
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
};

export const clearStoredAuth = () => {
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
};

export const configureAxiosAuth = (token) => {
  if (token) {
    axios.defaults.headers.common.Authorization = `Bearer ${token}`;
    return;
  }
  delete axios.defaults.headers.common.Authorization;
};

export const getWebSocketBaseUrl = () => getApiUrl().replace(/^http/, 'ws').replace(/\/api\/?$/, '');

export const buildWebSocketUrl = (path, token) => {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const url = new URL(`${getWebSocketBaseUrl()}${normalizedPath}`);
  if (token) {
    url.searchParams.set('token', token);
  }
  return url.toString();
};
