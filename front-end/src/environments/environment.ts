declare global {
  interface Window {
    __APP_API_URL__?: string;
  }
}

const runtimeApiUrl =
  (typeof window !== 'undefined' && window.__APP_API_URL__) ||
  (typeof globalThis !== 'undefined' && (globalThis as Record<string, string | undefined>).__APP_API_URL__);

export const environment = {
  production: false,
  apiUrl: runtimeApiUrl || 'http://localhost:8000/api',
};
