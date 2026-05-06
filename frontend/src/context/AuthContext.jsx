import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import {
  clearStoredAuth,
  configureAxiosAuth,
  getApiUrl,
  getStoredAuth,
  saveStoredAuth,
} from '../lib/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const storedAuth = getStoredAuth();
  const [token, setToken] = useState(storedAuth?.accessToken || '');
  const [user, setUser] = useState(storedAuth?.user || null);
  const [allowSelfRegistration, setAllowSelfRegistration] = useState(false);
  const [ready, setReady] = useState(false);
  const apiUrl = getApiUrl();

  const applySession = useCallback((accessToken, nextUser) => {
    setToken(accessToken || '');
    setUser(nextUser || null);
    configureAxiosAuth(accessToken || '');
    if (accessToken && nextUser) {
      saveStoredAuth({ accessToken, user: nextUser });
      return;
    }
    clearStoredAuth();
  }, []);

  useEffect(() => {
    configureAxiosAuth(token);
  }, [token]);

  useEffect(() => {
    let cancelled = false;

    const hydrate = async () => {
      try {
        const configRes = await axios.get(`${apiUrl}/auth/config`);
        if (!cancelled) {
          setAllowSelfRegistration(Boolean(configRes.data?.allow_self_registration));
        }
      } catch {
        if (!cancelled) {
          setAllowSelfRegistration(false);
        }
      }

      if (!token) {
        if (!cancelled) {
          setReady(true);
        }
        return;
      }

      try {
        const meRes = await axios.get(`${apiUrl}/auth/me`);
        if (!cancelled) {
          applySession(token, meRes.data);
        }
      } catch {
        if (!cancelled) {
          applySession('', null);
        }
      } finally {
        if (!cancelled) {
          setReady(true);
        }
      }
    };

    hydrate();

    return () => {
      cancelled = true;
    };
  }, [apiUrl, applySession, token]);

  const login = useCallback(async ({ username, password }) => {
    const response = await axios.post(`${apiUrl}/auth/login`, { username, password });
    applySession(response.data?.access_token || '', response.data?.user || null);
    return response.data?.user || null;
  }, [apiUrl, applySession]);

  const register = useCallback(async ({ username, password, fullName }) => {
    const response = await axios.post(`${apiUrl}/auth/register`, {
      username,
      password,
      full_name: fullName,
    });
    applySession(response.data?.access_token || '', response.data?.user || null);
    return response.data?.user || null;
  }, [apiUrl, applySession]);

  const logout = useCallback(() => {
    applySession('', null);
  }, [applySession]);

  const refreshUser = useCallback(async () => {
    if (!token) {
      return null;
    }
    const response = await axios.get(`${apiUrl}/auth/me`);
    applySession(token, response.data);
    return response.data;
  }, [apiUrl, applySession, token]);

  const value = useMemo(() => ({
    token,
    user,
    ready,
    allowSelfRegistration,
    isAdmin: user?.role === 'admin',
    login,
    register,
    logout,
    refreshUser,
  }), [allowSelfRegistration, login, logout, ready, refreshUser, register, token, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}