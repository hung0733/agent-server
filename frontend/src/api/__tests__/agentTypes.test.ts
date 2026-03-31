import { describe, it, expect, vi, beforeEach } from "vitest";
import { fetchAgentTypes, createAgentType, updateAgentType, deleteAgentType } from "../dashboard";

const MOCK_TYPE = {
  id: "type-1",
  name: "TestType",
  description: "A test type",
  isActive: true,
  createdAt: "2026-03-31T00:00:00Z",
};

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ agentTypes: [MOCK_TYPE] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
});

describe("fetchAgentTypes", () => {
  it("calls GET /api/dashboard/agent-types", async () => {
    const result = await fetchAgentTypes();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agent-types"),
      expect.objectContaining({}),
    );
    expect(result.agentTypes).toHaveLength(1);
    expect(result.agentTypes[0].name).toBe("TestType");
  });
});

describe("createAgentType", () => {
  it("calls POST /api/dashboard/agent-types with body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ agentType: MOCK_TYPE }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const result = await createAgentType({ name: "TestType", description: "A test type" });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agent-types"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.agentType.name).toBe("TestType");
  });
});

describe("updateAgentType", () => {
  it("calls PATCH /api/dashboard/agent-types/:id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ agentType: { ...MOCK_TYPE, name: "Updated" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const result = await updateAgentType("type-1", { name: "Updated" });
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agent-types/type-1"),
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(result.agentType.name).toBe("Updated");
  });
});

describe("deleteAgentType", () => {
  it("calls DELETE /api/dashboard/agent-types/:id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ deleted: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const result = await deleteAgentType("type-1");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/dashboard/agent-types/type-1"),
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(result.deleted).toBe(true);
  });
});
