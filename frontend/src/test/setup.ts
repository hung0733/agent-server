import "@testing-library/jest-dom/vitest";
import { beforeEach, vi } from "vitest";

import {
  agentsPayload,
  memoryPayload,
  overviewPayload,
  settingsPayload,
  tasksPayload,
  usagePayload,
} from "../mock/dashboard";

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof Request
          ? input.url
          : String(input);
    const payload = url.includes("/api/dashboard/usage")
      ? usagePayload
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
