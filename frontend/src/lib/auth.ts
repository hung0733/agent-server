const DASHBOARD_API_KEY_STORAGE_KEY = "dashboard_api_key";

export function getStoredApiKey(): string {
  return window.sessionStorage.getItem(DASHBOARD_API_KEY_STORAGE_KEY) ?? "";
}

export function setStoredApiKey(value: string): void {
  window.sessionStorage.setItem(DASHBOARD_API_KEY_STORAGE_KEY, value);
}

export function clearStoredApiKey(): void {
  window.sessionStorage.removeItem(DASHBOARD_API_KEY_STORAGE_KEY);
}
