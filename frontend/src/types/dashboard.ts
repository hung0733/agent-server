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
  summary: {
    title: string;
    body: string;
  };
  stats: Array<{
    title: string;
    value: number;
    note: string;
    status: Exclude<SystemStatus, "idle">;
  }>;
  recentEntries: Array<{
    id: string;
    title: string;
    detail: string;
    timestamp: string;
  }>;
  source: string;
}

export interface SettingsPayload {
  locales: string[];
  featureFlags: Record<string, boolean>;
  source: string;
}
