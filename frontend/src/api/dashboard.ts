import {
  AgentsPayload,
  MemoryPayload,
  OverviewPayload,
  SettingsPayload,
  TasksPayload,
  UsagePayload,
} from "../types/dashboard";

const API_BASE = import.meta.env.VITE_DASHBOARD_API_BASE ?? "";

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
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
