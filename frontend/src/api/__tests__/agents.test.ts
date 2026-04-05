import { describe, it, expect, vi, beforeEach } from "vitest";
import { bootstrapAgentSoul, createAgent, updateAgent } from "../dashboard";

const MOCK_AGENT = {
  id: "agent-1",
  name: "TestAgent",
  role: "",
  status: "healthy" as const,
  currentTask: "",
  latestOutput: "",
  scheduled: false,
  isActive: true,
  isSubAgent: false,
  phoneNo: null,
  whatsappKey: null,
  agentTypeId: "type-1",
  agentTypeName: "研究型員工",
};

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ agent: MOCK_AGENT }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
});

describe("createAgent", () => {
  it("calls POST /api/dashboard/agents with body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ agent: MOCK_AGENT }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const result = await createAgent({ name: "TestAgent", agentTypeId: "type-1" });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agents"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.agent.name).toBe("TestAgent");
    expect(result.agent.isActive).toBe(true);
    expect(result.agent.agentTypeId).toBe("type-1");
  });
});

describe("updateAgent", () => {
  it("calls PATCH /api/dashboard/agents/:id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ agent: { ...MOCK_AGENT, isActive: false } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const result = await updateAgent("agent-1", { isActive: false });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agents/agent-1"),
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(result.agent.isActive).toBe(false);
  });
});

describe("bootstrapAgentSoul", () => {
  it("calls POST /api/dashboard/agents/:id/bootstrap with body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          sessionId: "ghost-1",
          mode: "bootstrap",
          reply: "What kind of partner should I be?",
          saved: false,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const result = await bootstrapAgentSoul("agent-1", {
      message: "Start",
      history: [],
      save: false,
    });

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agents/agent-1/bootstrap"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.reply).toBe("What kind of partner should I be?");
    expect(result.saved).toBe(false);
  });
});
