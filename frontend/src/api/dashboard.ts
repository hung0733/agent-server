import {
  AgentCardData,
  AgentCreateBody,
  AgentToolUpdatePayload,
  AgentToolsPayload,
  AgentTypeItem,
  AgentTypeToolUpdatePayload,
  AgentTypesPayload,
  AgentUpdateBody,
  AgentsPayload,
  LTMPayload,
  MemoryBlocksInput,
  MemoryPayload,
  MessageScheduleInput,
  OverviewPayload,
  SchedulesPayload,
  SettingsPayload,
  STMPayload,
  TasksPayload,
  UsagePayload,
} from "../types/dashboard";
import { clearStoredApiKey, getStoredApiKey } from "../lib/auth";

const API_BASE = import.meta.env.VITE_DASHBOARD_API_BASE ?? "";
export const DASHBOARD_AUTH_EXPIRED_EVENT = "dashboard-auth-expired";

async function requestJson<T>(path: string): Promise<T> {
  return requestJsonWithKey<T>(path, getStoredApiKey());
}

async function requestJsonWithKey<T>(path: string, apiKey: string): Promise<T> {
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

async function mutateJson<T>(path: string, method: string, body: unknown): Promise<T> {
  const apiKey = getStoredApiKey();
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      ...(apiKey ? { "X-API-Key": apiKey } : {}),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (response.status === 401) {
    clearStoredApiKey();
    window.dispatchEvent(new CustomEvent(DASHBOARD_AUTH_EXPIRED_EVENT));
    throw new Error("Dashboard API unauthorized");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error ?? `Dashboard API request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchOverview(): Promise<OverviewPayload> {
  return requestJson<OverviewPayload>("/api/dashboard/overview");
}

export function fetchOverviewWithApiKey(apiKey: string): Promise<OverviewPayload> {
  return requestJsonWithKey<OverviewPayload>("/api/dashboard/overview", apiKey);
}

export function fetchUsage(): Promise<UsagePayload> {
  return requestJson<UsagePayload>("/api/dashboard/usage");
}

export function fetchAgents(): Promise<AgentsPayload> {
  return requestJson<AgentsPayload>("/api/dashboard/agents");
}

export function fetchTasks(before?: string): Promise<TasksPayload> {
  const url = before 
    ? `/api/dashboard/tasks?before=${encodeURIComponent(before)}`
    : "/api/dashboard/tasks";
  return requestJson<TasksPayload>(url);
}

export function fetchMemory(): Promise<MemoryPayload> {
  return requestJson<MemoryPayload>("/api/dashboard/memory");
}

export function fetchSchedules(): Promise<SchedulesPayload> {
  return requestJson<SchedulesPayload>("/api/dashboard/schedules");
}

export function createMessageSchedule(body: MessageScheduleInput): Promise<{ schedule: SchedulesPayload["messageSchedules"][number] }> {
  return mutateJson("/api/dashboard/schedules/message", "POST", body);
}

export function updateMessageSchedule(
  scheduleId: string,
  body: Partial<MessageScheduleInput>,
): Promise<{ schedule: SchedulesPayload["messageSchedules"][number] }> {
  return mutateJson(`/api/dashboard/schedules/message/${scheduleId}`, "PATCH", body);
}

export function deleteMessageSchedule(scheduleId: string): Promise<{ deleted: boolean }> {
  return mutateJson(`/api/dashboard/schedules/message/${scheduleId}`, "DELETE", {});
}

export function refreshMessageSchedule(
  scheduleId: string,
): Promise<{ schedule: SchedulesPayload["messageSchedules"][number] }> {
  return mutateJson(`/api/dashboard/schedules/message/${scheduleId}/refresh`, "POST", {});
}

export function fetchSTM(): Promise<STMPayload> {
  return requestJson<STMPayload>("/api/dashboard/stm");
}

export function fetchLTM(cursor?: string): Promise<LTMPayload> {
  const url = cursor 
    ? `/api/dashboard/ltm?cursor=${encodeURIComponent(cursor)}`
    : "/api/dashboard/ltm";
  return requestJson<LTMPayload>(url);
}

export function fetchSettings(): Promise<SettingsPayload> {
  return requestJson<SettingsPayload>("/api/dashboard/settings");
}

export function fetchAgentTools(): Promise<AgentToolsPayload> {
  return requestJson<AgentToolsPayload>("/api/dashboard/agents/tools");
}

export function fetchAgentMemoryBlocks(id: string): Promise<MemoryBlocksInput> {
  return requestJson<MemoryBlocksInput>(`/api/dashboard/agents/${id}/memory-blocks`);
}

export function updateAgentTool(
  agentId: string,
  toolId: string,
  body: unknown,
): Promise<AgentToolUpdatePayload> {
  return mutateJson(`/api/dashboard/agents/${agentId}/tools/${toolId}`, "PATCH", body);
}

export function updateAgentTypeTool(
  agentTypeId: string,
  toolId: string,
  body: unknown,
): Promise<AgentTypeToolUpdatePayload> {
  return mutateJson(`/api/dashboard/agent-types/${agentTypeId}/tools/${toolId}`, "PATCH", body);
}

export function createSettingsEndpoint(body: unknown): Promise<{ endpoint: SettingsPayload["endpoints"][number] }> {
  return mutateJson("/api/dashboard/settings/endpoints", "POST", body);
}

export function updateSettingsEndpoint(
  endpointId: string,
  body: unknown,
): Promise<{ endpoint: SettingsPayload["endpoints"][number] }> {
  return mutateJson(`/api/dashboard/settings/endpoints/${endpointId}`, "PATCH", body);
}

export function deleteSettingsEndpoint(endpointId: string): Promise<{ deleted: boolean }> {
  return mutateJson(`/api/dashboard/settings/endpoints/${endpointId}`, "DELETE", {});
}

export function saveSettingsMapping(body: unknown): Promise<{ mapping: SettingsPayload["groups"][number]["slots"][number] | null }> {
  return mutateJson("/api/dashboard/settings/mappings", "PUT", body);
}

export function createAuthKey(body: unknown): Promise<{ key: SettingsPayload["authKeys"][number]; rawKey: string }> {
  return mutateJson("/api/dashboard/settings/auth-keys", "POST", body);
}

export function updateAuthKey(
  keyId: string,
  body: unknown,
): Promise<{ key: SettingsPayload["authKeys"][number] }> {
  return mutateJson(`/api/dashboard/settings/auth-keys/${keyId}`, "PATCH", body);
}

export function deleteAuthKey(keyId: string): Promise<{ deleted: boolean }> {
  return mutateJson(`/api/dashboard/settings/auth-keys/${keyId}`, "DELETE", {});
}

export function regenerateAuthKey(
  keyId: string,
  body: unknown,
): Promise<{ key: SettingsPayload["authKeys"][number]; rawKey: string }> {
  return mutateJson(`/api/dashboard/settings/auth-keys/${keyId}/regenerate`, "POST", body);
}

export function createAgent(body: AgentCreateBody): Promise<{ agent: AgentCardData }> {
  return mutateJson("/api/dashboard/agents", "POST", body);
}

export function updateAgent(id: string, body: AgentUpdateBody): Promise<{ agent: AgentCardData }> {
  return mutateJson(`/api/dashboard/agents/${id}`, "PATCH", body);
}

export function fetchAgentTypes(): Promise<AgentTypesPayload> {
  return requestJson<AgentTypesPayload>("/api/dashboard/agent-types");
}

export function createAgentType(
  body: { name: string; description?: string; isActive?: boolean },
): Promise<{ agentType: AgentTypeItem }> {
  return mutateJson("/api/dashboard/agent-types", "POST", body);
}

export function updateAgentType(
  id: string,
  body: { name?: string; description?: string; isActive?: boolean },
): Promise<{ agentType: AgentTypeItem }> {
  return mutateJson(`/api/dashboard/agent-types/${id}`, "PATCH", body);
}

export function deleteAgentType(id: string): Promise<{ deleted: boolean }> {
  return mutateJson(`/api/dashboard/agent-types/${id}`, "DELETE", {});
}
