export type SystemStatus = "healthy" | "warning" | "danger" | "idle";

export interface OverviewSummary {
  score: number;
  headline: string;
  conclusion: string;
  status: SystemStatus;
  requiresIntervention: boolean;
}

export interface StatMetric {
  label: string;
  value: number;
  note: string;
  status: SystemStatus;
}

export interface AgentSummary {
  id: string;
  name: string;
  role: string;
  status: SystemStatus;
}

export interface AgentCardData extends AgentSummary {
  currentTask: string;
  latestOutput: string;
  scheduled: boolean;
}

export interface TimelineItem {
  id: string;
  type: string;
  sourceAgent: string;
  targetAgent: string;
  group?: string;
  messageSnippet?: string;
  title: string;
  summary: string;
  timestamp: string;
  status: SystemStatus;
  technicalDetails: string;
}

export interface UsageLegendItem {
  label: string;
  value: number;
  percentage: number;
  color: string;
}

export interface ShellMeta {
  lastUpdatedAt: string;
}

export interface RailSummary {
  usageText: string;
  activeAgentNames: string;
  scheduleCount?: number;
}

export interface OverviewPayload {
  summary: OverviewSummary;
  stats: StatMetric[];
  activeAgents: AgentCardData[];
  shellMeta: ShellMeta;
  railSummary: RailSummary;
  intervention: {
    title: string;
    body: string;
    source: string;
  };
  source: string;
}

export interface UsagePayload {
  total: number;
  items: UsageLegendItem[];
  todayTokens: number;
  todayCostUsd: string;
  source: string;
}

export interface AgentsPayload {
  agents: AgentCardData[];
  source: string;
}

export interface TasksPayload {
  items: TimelineItem[];
  source: string;
}

export interface MemoryPayload {
  stats: {
    agents: number;
    tasks: number;
    messages: number;
  };
  health: {
    status: SystemStatus;
    summary: string;
  };
  recentEntries: Array<{
    kind: string;
    timestamp: string;
    agent: string;
    summary: string;
    status: SystemStatus;
  }>;
  source: string;
}

export interface SettingsPayload {
  locales: string[];
  featureFlags: Record<string, boolean>;
  endpoints: Array<{
    id: string;
    name: string;
    baseUrl: string;
    modelName: string;
    isActive: boolean;
    apiKeyConfigured: boolean;
  }>;
  groups: Array<{
    id: string;
    name: string;
    slots: Array<{
      id: string;
      difficultyLevel: number;
      involvesSecrets: boolean;
      endpointId: string;
      priority: number;
      isActive: boolean;
    }>;
  }>;
  authKeys: Array<{
    id: string;
    name: string;
    isActive: boolean;
    lastUsedAt: string | null;
    expiresAt: string | null;
    createdAt: string | null;
  }>;
  source: string;
}

export interface AgentToolDefinition {
  id: string;
  name: string;
  description: string;
  isActive: boolean;
}

export interface AgentToolState extends AgentToolDefinition {
  isEnabled: boolean;
  source: "type" | "override" | "inactive";
}

export interface AgentToolsAgent extends AgentSummary {
  tools: AgentToolState[];
}

export interface AgentToolsPayload {
  agents: AgentToolsAgent[];
  availableTools: AgentToolDefinition[];
  source: string;
}

export interface AgentToolUpdatePayload {
  tool: {
    id: string;
    agentInstanceId: string;
    toolId: string;
    isEnabled: boolean;
    configOverride: Record<string, unknown> | null;
  };
}

export interface AgentTypeItem {
  id: string;
  name: string;
  description: string | null;
  isActive: boolean;
  createdAt: string;
}

export interface AgentTypesPayload {
  agentTypes: AgentTypeItem[];
}
