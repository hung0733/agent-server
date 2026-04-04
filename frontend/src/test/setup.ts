import "@testing-library/jest-dom/vitest";
import { beforeEach, vi } from "vitest";

import {
  agentToolUpdatePayload,
  agentToolsPayload,
  agentTypesPayload,
  agentsPayload,
  memoryPayload,
  overviewPayload,
  schedulesPayload,
  settingsPayload,
  tasksPayload,
  usagePayload,
} from "../mock/dashboard";

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof Request
          ? input.url
          : String(input);
    const method = init?.method ?? (input instanceof Request ? input.method : "GET");
    if (url.includes("/api/dashboard/agents/") && url.includes("/tools/") && method === "PATCH") {
      return Promise.resolve(
        new Response(JSON.stringify(agentToolUpdatePayload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.includes("/api/dashboard/schedules/message") && method === "DELETE") {
      return Promise.resolve(
        new Response(JSON.stringify({ deleted: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.includes("/api/dashboard/schedules/message") && method === "PATCH") {
      return Promise.resolve(
        new Response(JSON.stringify({ schedule: schedulesPayload.messageSchedules[0] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.includes("/api/dashboard/schedules/message") && method === "POST") {
      return Promise.resolve(
        new Response(JSON.stringify({ schedule: schedulesPayload.messageSchedules[0] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.includes("/api/dashboard/agent-types")) {
      return Promise.resolve(
        new Response(JSON.stringify(agentTypesPayload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    const payload = url.includes("/api/dashboard/usage")
      ? usagePayload
      : url.includes("/api/dashboard/schedules")
        ? schedulesPayload
      : url.includes("/api/dashboard/agents/tools")
        ? agentToolsPayload
      : url.includes("/api/dashboard/agents")
        ? agentsPayload
      : url.includes("/api/dashboard/tasks")
        ? tasksPayload
          : url.includes("/api/dashboard/memory")
            ? memoryPayload
            : url.includes("/api/dashboard/settings")
              ? settingsPayload
              : overviewPayload;

    return Promise.resolve(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
});
