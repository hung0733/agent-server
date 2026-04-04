import { vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";

import ScheduleTab from "../ScheduleTab";
import { renderWithRouter } from "../../../test/render";
import { fetchAgents, fetchSchedules } from "../../../api/dashboard";

vi.mock("../../../api/dashboard");

describe("ScheduleTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows empty states instead of mock schedule data when loading fails", async () => {
    vi.mocked(fetchSchedules).mockRejectedValue(new Error("boom"));
    vi.mocked(fetchAgents).mockRejectedValue(new Error("boom"));

    renderWithRouter(<ScheduleTab />);

    await waitFor(() => {
      expect(screen.getByText("目前未有 method 排程。")).toBeInTheDocument();
    });

    expect(screen.getByText("目前未有 message 排程。")).toBeInTheDocument();
    expect(screen.queryByText("Daily review")).not.toBeInTheDocument();
    expect(screen.queryByText("Morning ping")).not.toBeInTheDocument();
  });
});
