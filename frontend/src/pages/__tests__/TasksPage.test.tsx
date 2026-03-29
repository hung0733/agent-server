import { vi } from "vitest";

import { useDashboardResource } from "../../hooks/useDashboardResource";
import { renderWithRouter, screen } from "../../test/render";
import TasksPage from "../TasksPage";

vi.mock("../../hooks/useDashboardResource", () => ({
  useDashboardResource: vi.fn(),
}));

describe("TasksPage", () => {
  it("uses an empty payload fallback instead of mock task content", () => {
    vi.mocked(useDashboardResource).mockReturnValue({
      isLoading: false,
      resource: {
        items: [],
        source: "test",
      },
    });

    renderWithRouter(<TasksPage />);

    expect(vi.mocked(useDashboardResource)).toHaveBeenCalledWith(
      expect.any(Function),
      {
        items: [],
        source: "empty",
      },
      {
        blockOnFirstLoad: true,
      },
    );
  });

  it("renders an empty state when no task activity is available", () => {
    vi.mocked(useDashboardResource).mockReturnValue({
      isLoading: false,
      resource: {
        items: [],
        source: "test",
      },
    });

    renderWithRouter(<TasksPage />);

    expect(screen.getByText("最近未見跨會話活動")).toBeInTheDocument();
    expect(screen.getByText("目前未有可顯示的排程、任務或協作事件。")).toBeInTheDocument();
  });
});
