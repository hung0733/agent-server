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
  isActive: boolean;
  isSubAgent: boolean;
  phoneNo: string | null;
  whatsappKey: string | null;
  agentTypeId: string | null;
  agentTypeName: string | null;
  endpointGroupId: string | null;
}

export interface AgentCreateBody {
  name: string;
  agentTypeId: string;
  agentId?: string;
  phoneNo?: string;
  whatsappKey?: string;
  isActive?: boolean;
  isSubAgent?: boolean;
  endpointGroupId?: string;
  memoryBlocks?: MemoryBlocksInput;
}

export interface AgentUpdateBody {
  name?: string;
  agentTypeId?: string;
  phoneNo?: string;
  whatsappKey?: string;
  isActive?: boolean;
  isSubAgent?: boolean;
  endpointGroupId?: string;
  memoryBlocks?: MemoryBlocksInput;
}

export interface MemoryBlocksInput {
  SOUL?: string;
  USER_PROFILE?: string;
  IDENTITY?: string;
}

export interface BootstrapChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AgentBootstrapRequest {
  message: string;
  history: BootstrapChatMessage[];
  mode?: "bootstrap" | "synthesis" | "build";
  save?: boolean;
  previewPrompt?: boolean;
}

export interface AgentBootstrapResponse {
  sessionId: string;
  mode: "bootstrap" | "synthesis" | "build";
  reply?: string;
  saved?: boolean;
  soul?: string;
  message?: string;
  systemPrompt?: string;
  availableModes?: string[];
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

export type ScheduleTaskType = "method" | "message";
export type EditableScheduleType = "cron" | "interval";

export interface ScheduleItem {
  id: string;
  taskId: string;
  taskType: ScheduleTaskType;
  name: string;
  prompt: string;
  scheduleType: EditableScheduleType;
  scheduleExpression: string;
  isActive: boolean;
  nextRunAt: string | null;
  lastRunAt: string | null;
  agentId: string | null;
  agentName: string | null;
}

export interface SchedulesPayload {
  methodSchedules: ScheduleItem[];
  messageSchedules: ScheduleItem[];
  source: string;
}

export interface MessageScheduleInput {
  agentId: string;
  name: string;
  prompt: string;
  scheduleType: EditableScheduleType;
  scheduleExpression: string;
  isActive: boolean;
}

export interface TasksPayload {
  items: TimelineItem[];
  source: string;
  hasMore: boolean;
  nextCursor: string | null;
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

export interface STMEntry {
  id: string;
  kind: "stm";
  agent: string;
  timestamp: string;
  summary: string;
  sessionId: string;
  sessionName: string;
  status: SystemStatus;
}

export interface LTMEntry {
  id: string;
  kind: "ltm";
  agent: string;
  timestamp: string;
  summary: string;
  status: SystemStatus;
}

export interface STMPayload {
  entries: STMEntry[];
  hasMore: false;
  source: string;
}

export interface LTMPayload {
  entries: LTMEntry[];
  hasMore: boolean;
  nextCursor: string | null;
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
  agentTypes: AgentToolsAgent[];
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

export interface AgentTypeToolUpdatePayload {
  tool: {
    id: string;
    agentTypeId: string;
    toolId: string;
    isActive: boolean;
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
