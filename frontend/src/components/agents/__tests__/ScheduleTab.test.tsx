import { vi, beforeEach, describe, it, expect } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ScheduleTab from "../ScheduleTab";
import { renderWithRouter } from "../../../test/render";
import * as dashboardApi from "../../../api/dashboard";

vi.mock("../../../api/dashboard", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/dashboard")>();
  return {
    ...actual,
    fetchSchedules: vi.fn(),
    fetchAgents: vi.fn(),
    executeSchedule: vi.fn(),
  };
});

describe("ScheduleTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows empty states instead of mock schedule data when loading fails", async () => {
    vi.mocked(dashboardApi.fetchSchedules).mockRejectedValue(new Error("boom"));
    vi.mocked(dashboardApi.fetchAgents).mockRejectedValue(new Error("boom"));

    renderWithRouter(<ScheduleTab />);

    await waitFor(() => {
      expect(screen.getByText("目前未有 method 排程。")).toBeInTheDocument();
    });

    expect(screen.getByText("目前未有 message 排程。")).toBeInTheDocument();
    expect(screen.queryByText("Daily review")).not.toBeInTheDocument();
    expect(screen.queryByText("Morning ping")).not.toBeInTheDocument();
  });
});

describe("ScheduleTab Run button", () => {
  const schedulesPayload = {
    methodSchedules: [
      {
        id: "schedule-method-1",
        taskId: "task-method-1",
        taskType: "method",
        name: "Daily review",
        prompt: "agent.bulter@Bulter.review_ltm",
        scheduleType: "cron",
        scheduleExpression: "0 16 * * *",
        isActive: true,
        nextRunAt: "2026-04-04T16:00:00+08:00",
        lastRunAt: "2026-04-03T16:00:00+08:00",
        agentId: "otter",
        agentName: "otter",
      },
    ],
    messageSchedules: [
      {
        id: "schedule-message-1",
        taskId: "task-message-1",
        taskType: "message",
        name: "Morning ping",
        prompt: "send summary",
        scheduleType: "interval",
        scheduleExpression: "PT2H",
        isActive: true,
        nextRunAt: "2026-04-04T10:00:00+08:00",
        lastRunAt: null,
        agentId: "main",
        agentName: "main",
      },
    ],
    source: "mock",
  };

  const agentsPayload = {
    agents: [
      {
        id: "main",
        name: "main",
        role: "主控與協調",
        status: "healthy",
        currentTask: "",
        latestOutput: "",
        scheduled: true,
        isActive: true,
        isSubAgent: false,
        phoneNo: null,
        whatsappKey: null,
        agentTypeId: null,
        agentTypeName: null,
        endpointGroupId: null,
      },
    ],
    source: "mock",
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(dashboardApi.fetchSchedules).mockResolvedValue(schedulesPayload);
    vi.mocked(dashboardApi.fetchAgents).mockResolvedValue(agentsPayload);
  });

  it("renders Run button in message schedule actions", async () => {
    renderWithRouter(<ScheduleTab />);

    await screen.findByText("Morning ping");

    const messageScheduleCard = screen.getByText("Morning ping").closest("article")!;
    expect(within(messageScheduleCard).getByRole("button", { name: "執行" })).toBeInTheDocument();
  });

  it("shows success message when Run button clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(dashboardApi.executeSchedule).mockResolvedValue({
      success: true,
      taskId: "test-task-id",
    });

    renderWithRouter(<ScheduleTab />);

    await screen.findByText("Morning ping");

    const messageScheduleCard = screen.getByText("Morning ping").closest("article")!;
    await user.click(within(messageScheduleCard).getByRole("button", { name: "執行" }));

    await waitFor(() => {
      expect(screen.getByText("任務已啟動")).toBeInTheDocument();
    });

    expect(vi.mocked(dashboardApi.executeSchedule)).toHaveBeenCalledWith("schedule-message-1");
  });

  it("shows error message when Run fails", async () => {
    const user = userEvent.setup();
    vi.mocked(dashboardApi.executeSchedule).mockRejectedValue(new Error("Internal server error"));

    renderWithRouter(<ScheduleTab />);

    await screen.findByText("Morning ping");

    const messageScheduleCard = screen.getByText("Morning ping").closest("article")!;
    await user.click(within(messageScheduleCard).getByRole("button", { name: "執行" }));

    await waitFor(() => {
      expect(screen.getByText("Internal server error")).toBeInTheDocument();
    });
  });

  it("shows specific error for missing agent", async () => {
    const user = userEvent.setup();
    vi.mocked(dashboardApi.executeSchedule).mockRejectedValue(new Error("schedule_missing_agent"));

    renderWithRouter(<ScheduleTab />);

    await screen.findByText("Morning ping");

    const messageScheduleCard = screen.getByText("Morning ping").closest("article")!;
    await user.click(within(messageScheduleCard).getByRole("button", { name: "執行" }));

    await waitFor(() => {
      expect(screen.getByText("排程缺少 Agent，請先設定 Agent")).toBeInTheDocument();
    });
  });
});