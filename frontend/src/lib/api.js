export const getApiUrl = () => {
  const envUrl = (import.meta?.env?.VITE_API_URL || '').trim();
  if (envUrl) return envUrl;
  const hostname = window.location.hostname || 'localhost';
  return `http://${hostname}:8001/api`;
};
