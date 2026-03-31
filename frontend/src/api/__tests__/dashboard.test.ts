import { describe, expect, it, vi } from "vitest";

import { fetchAgentTools, updateAgentTool } from "../dashboard";

describe("dashboard api", () => {
  it("fetches agent tools payload", async () => {
    const payload = await fetchAgentTools();

    expect(payload.source).toBe("mock");
    expect(payload.agents).toHaveLength(2);
    expect(payload.availableTools).toHaveLength(2);
  });

  it("updates an agent tool override", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy.mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
      if (url.includes("/api/dashboard/agents/agent-1/tools/tool-1")) {
        expect(init?.method).toBe("PATCH");
        return new Response(
          JSON.stringify({
            tool: {
              id: "override-1",
              agentInstanceId: "agent-1",
              toolId: "tool-1",
              isEnabled: false,
              configOverride: null,
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }

      return new Response("not found", { status: 404 });
    });

    const payload = await updateAgentTool("agent-1", "tool-1", { isEnabled: false });

    expect(payload.tool.id).toBe("override-1");
    expect(payload.tool.isEnabled).toBe(false);
  });
});
