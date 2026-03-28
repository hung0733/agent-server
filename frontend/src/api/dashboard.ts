import {
  AgentsPayload,
  MemoryPayload,
  OverviewPayload,
  SettingsPayload,
  TasksPayload,
  UsagePayload,
} from "../types/dashboard";
import { clearStoredApiKey, getStoredApiKey } from "../lib/auth";

const API_BASE = import.meta.env.VITE_DASHBOARD_API_BASE ?? "";
export const DASHBOARD_AUTH_EXPIRED_EVENT = "dashboard-auth-expired";

async function requestJson<T>(path: string): Promise<T> {
  const apiKey = getStoredApiKey();
  const response = await fetch(`${API_BASE}${path}`, {
    headers: apiKey ? { "X-API-Key": apiKey } : {},
  });
  if (response.status === 401) {
    clearStoredApiKey();
    window.dispatchEvent(new CustomEvent(DASHBOARD_AUTH_EXPIRED_EVENT));
    throw new Error("Dashboard API unauthorized");
  }
  if (!response.ok) {
    throw new Error(`Dashboard API request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchOverview(): Promise<OverviewPayload> {
  return requestJson<OverviewPayload>("/api/dashboard/overview");
}

export function fetchUsage(): Promise<UsagePayload> {
  return requestJson<UsagePayload>("/api/dashboard/usage");
}

export function fetchAgents(): Promise<AgentsPayload> {
  return requestJson<AgentsPayload>("/api/dashboard/agents");
}

export function fetchTasks(): Promise<TasksPayload> {
  return requestJson<TasksPayload>("/api/dashboard/tasks");
}

export function fetchMemory(): Promise<MemoryPayload> {
  return requestJson<MemoryPayload>("/api/dashboard/memory");
}

export function fetchSettings(): Promise<SettingsPayload> {
  return requestJson<SettingsPayload>("/api/dashboard/settings");
}
