import {
  AgentToolDefinition,
  AgentToolUpdatePayload,
  AgentToolsPayload,
  AgentTypeItem,
  AgentTypesPayload,
  AgentCardData,
  AgentSummary,
  AgentsPayload,
  MemoryPayload,
  OverviewSummary,
  OverviewPayload,
  RailSummary,
  SettingsPayload,
  ShellMeta,
  StatMetric,
  TimelineItem,
  TasksPayload,
  UsagePayload,
  UsageLegendItem,
} from "../types/dashboard";

export const overviewSummary: OverviewSummary = {
  score: 92,
  headline: "推進順暢",
  conclusion: "系統整體穩定，今日未見需要立即升級處理的事件。",
  status: "healthy",
  requiresIntervention: false,
};

export const overviewStats: StatMetric[] = [
  { label: "待審批", value: 2, note: "2 項待人工確認", status: "warning" },
  { label: "運行異常", value: 1, note: "1 項需留意", status: "warning" },
  { label: "停滯任務", value: 0, note: "目前無需介入", status: "healthy" },
  { label: "預算風險", value: 0, note: "今日預算安全", status: "healthy" },
];

export const activeAgents: AgentSummary[] = [
  { id: "main", name: "main", role: "主控與協調", status: "healthy" },
  { id: "otter", name: "otter", role: "私人助理與提醒", status: "healthy" },
  { id: "pandas", name: "pandas", role: "控制中心交付", status: "warning" },
];

export const shellMeta: ShellMeta = {
  lastUpdatedAt: "2026-03-28T20:30:00+08:00",
};

export const railSummary: RailSummary = {
  usageText: "1,509,786 tokens / $0.81",
  activeAgentNames: "main, otter, pandas",
};

export const agents: AgentCardData[] = [
  {
    id: "main",
    name: "main",
    role: "主控與協調",
    status: "healthy",
    currentTask: "creators-sales-lead-radar",
    latestOutput: "完成第一輪審查摘要",
    scheduled: true,
    isActive: true,
    isSubAgent: false,
    phoneNo: null,
    whatsappKey: null,
    agentTypeId: "type-research",
    agentTypeName: "研究型員工",
  },
  {
    id: "otter",
    name: "otter",
    role: "私人助理與提醒",
    status: "healthy",
    currentTask: "daily-briefing-07-30",
    latestOutput: "已整理今日待辦與重點郵件",
    scheduled: true,
    isActive: true,
    isSubAgent: true,
    phoneNo: "+852 9000 0001",
    whatsappKey: null,
    agentTypeId: "type-assistant",
    agentTypeName: "助理型員工",
  },
  {
    id: "pandas",
    name: "pandas",
    role: "控制中心交付",
    status: "warning",
    currentTask: "等待可審查輸入",
    latestOutput: "目前缺少可審查輸入",
    scheduled: false,
    isActive: false,
    isSubAgent: false,
    phoneNo: null,
    whatsappKey: null,
    agentTypeId: "type-research",
    agentTypeName: "研究型員工",
  },
];

export const taskTimeline: TimelineItem[] = [
  {
    id: "evt-1",
    type: "announce",
    sourceAgent: "Main",
    targetAgent: "Pandas",
    title: "發起跨會話消息",
    summary: "請回覆最新狀態與最大阻塞",
    timestamp: "1 小時前",
    status: "healthy",
    technicalDetails: "sessions_send",
  },
  {
    id: "evt-2",
    type: "reply",
    sourceAgent: "Pandas",
    targetAgent: "Main",
    group: "內容審批",
    messageSnippet: "等緊新一批可審查內容先可以繼續。",
    title: "通過既有會話回信",
    summary: "目前缺的不是任務，而是可審查輸入。",
    timestamp: "58 分鐘前",
    status: "warning",
    technicalDetails: "announce_step",
  },
];

export const scheduledUsage: UsageLegendItem[] = [
  { label: "x-radar-collect", value: 95081, percentage: 16.58, color: "#80a9ff" },
  { label: "daily-digest-daily", value: 68841, percentage: 12.0, color: "#f0b45a" },
  { label: "Coq-每日新聞 08:00", value: 49199, percentage: 8.58, color: "#ff7b72" },
  { label: "x-radar-finalize", value: 48821, percentage: 8.51, color: "#49c6a8" },
];

export const overviewPayload: OverviewPayload = {
  summary: overviewSummary,
  stats: overviewStats,
  activeAgents: agents,
  shellMeta,
  railSummary,
  intervention: {
    title: "兩項審批等待確認",
    body: "Main 正整理可交付摘要，Pandas 正等待可審查輸入。",
    source: "mock",
  },
  source: "mock",
};

export const usagePayload: UsagePayload = {
  total: 573681,
  items: scheduledUsage,
  todayTokens: 1509786,
  todayCostUsd: "0.81",
  source: "mock",
};

export const agentsPayload: AgentsPayload = {
  agents,
  source: "mock",
};

export const availableTools: AgentToolDefinition[] = [
  {
    id: "tool-web-search",
    name: "web_search",
    description: "搜尋公開資料與網頁內容",
    isActive: true,
  },
  {
    id: "tool-file-reader",
    name: "file_reader",
    description: "讀取與摘要檔案內容",
    isActive: true,
  },
];

export const agentToolsPayload: AgentToolsPayload = {
  agents: [
    {
      ...agents[0],
      tools: [
        { ...availableTools[0], isEnabled: true, source: "type" },
        { ...availableTools[1], isEnabled: false, source: "override" },
      ],
    },
    {
      ...agents[1],
      tools: [
        { ...availableTools[0], isEnabled: true, source: "type" },
        { ...availableTools[1], isEnabled: true, source: "type" },
      ],
    },
  ],
  availableTools,
  source: "mock",
};

export const agentToolUpdatePayload: AgentToolUpdatePayload = {
  tool: {
    id: "override-1",
    agentInstanceId: "main",
    toolId: "tool-web-search",
    isEnabled: false,
    configOverride: null,
  },
};

export const tasksPayload: TasksPayload = {
  items: taskTimeline,
  source: "mock",
};

export const memoryPayload: MemoryPayload = {
  stats: {
    agents: 3,
    tasks: 1,
    messages: 2,
  },
  health: {
    status: "healthy",
    summary: "最近 3 項用戶活動可歸因。",
  },
  recentEntries: [
    {
      kind: "message",
      agent: "Main",
      summary: "客戶升級要求已完成摘要。",
      timestamp: "2026-03-29T10:28:00+08:00",
      status: "healthy",
    },
    {
      kind: "task",
      agent: "Pandas",
      summary: "部署事故跟進已補寫長期記憶。",
      timestamp: "2026-03-29T10:19:00+08:00",
      status: "warning",
    },
  ],
  source: "mock",
};

export const settingsPayload: SettingsPayload = {
  locales: ["zh-HK", "en"],
  featureFlags: {
    dashboardApi: true,
  },
  endpoints: [
    {
      id: "endpoint-1",
      name: "Local Qwen",
      baseUrl: "http://localhost:8601/v1",
      modelName: "qwen3.5-35b-a3b",
      isActive: true,
      apiKeyConfigured: true,
    },
  ],
  groups: [
    {
      id: "group-1",
      name: "Default Group",
      slots: [
        {
          id: "slot-1",
          difficultyLevel: 1,
          involvesSecrets: false,
          endpointId: "endpoint-1",
          priority: 0,
          isActive: true,
        },
      ],
    },
  ],
  authKeys: [
    {
      id: "key-1",
      name: "Dashboard main",
      isActive: true,
      lastUsedAt: "2026-03-29T18:00:00+08:00",
      expiresAt: null,
      createdAt: "2026-03-28T10:00:00+08:00",
    },
  ],
  source: "mock",
};

export const agentTypesPayload: AgentTypesPayload = {
  agentTypes: [
    {
      id: "type-research",
      name: "研究型員工",
      description: "負責網絡搜尋與資料整理",
      isActive: true,
      createdAt: "2026-03-01T00:00:00Z",
    },
    {
      id: "type-assistant",
      name: "助理型員工",
      description: "處理日常行政與提醒工作",
      isActive: true,
      createdAt: "2026-03-02T00:00:00Z",
    },
  ],
};
