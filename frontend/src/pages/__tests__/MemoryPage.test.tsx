import { renderWithRouter, screen } from "../../test/render";
import { MemoryPayload } from "../../types/dashboard";
import { vi } from "vitest";

import MemoryPage from "../MemoryPage";
import { useDashboardResource } from "../../hooks/useDashboardResource";

vi.mock("../../hooks/useDashboardResource", () => ({
  useDashboardResource: vi.fn(),
}));

const memoryFixture: MemoryPayload = {
  stats: {
    agents: 2,
    tasks: 1,
    messages: 1,
  },
  health: {
    status: "healthy",
    summary: "最近 2 項用戶活動可歸因。",
  },
  recentEntries: [
    {
      kind: "message",
      agent: "Beta",
      summary: "2 分鐘前完成摘要",
      timestamp: "2026-03-29T10:00:00+08:00",
      status: "healthy",
    },
    {
      kind: "task",
      agent: "Alpha",
      summary: "11 分鐘前補寫長期記憶",
      timestamp: "2026-03-29T09:51:00+08:00",
      status: "warning",
    },
  ],
  source: "test",
};

describe("MemoryPage", () => {
  it("renders backend memory health, counts, and recent entries", () => {
    vi.mocked(useDashboardResource).mockReturnValue({
      isLoading: false,
      resource: memoryFixture,
    });

    renderWithRouter(<MemoryPage />);

    expect(screen.getByText("最近 2 項用戶活動可歸因。")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getAllByText("1")).toHaveLength(2);
    expect(screen.getByText(/Beta/)).toBeInTheDocument();
    expect(screen.getByText("2026-03-29 10:00:00")).toBeInTheDocument();
    expect(screen.getByText("2 分鐘前完成摘要")).toBeInTheDocument();
    expect(screen.getByText(/Alpha/)).toBeInTheDocument();
    expect(screen.getByText("2026-03-29 09:51:00")).toBeInTheDocument();
    expect(screen.getByText("11 分鐘前補寫長期記憶")).toBeInTheDocument();
  });

  it("uses an empty payload fallback instead of mock memory content", () => {
    vi.mocked(useDashboardResource).mockReturnValue({
      isLoading: false,
      resource: memoryFixture,
    });

    renderWithRouter(<MemoryPage />);

    expect(vi.mocked(useDashboardResource)).toHaveBeenCalledWith(
      expect.any(Function),
      {
        stats: {
          agents: 0,
          tasks: 0,
          messages: 0,
        },
        health: {
          status: "idle",
          summary: "",
        },
        recentEntries: [],
        source: "empty",
      },
      {
        blockOnFirstLoad: true,
      },
    );
  });

  it("renders empty state when there is no memory activity", () => {
    vi.mocked(useDashboardResource).mockReturnValue({
      isLoading: false,
      resource: {
        ...memoryFixture,
        stats: {
          agents: 0,
          tasks: 0,
          messages: 0,
        },
        health: {
          status: "idle",
          summary: "",
        },
        recentEntries: [],
      },
    });

    renderWithRouter(<MemoryPage />);

    expect(screen.getByText("最近記憶寫入穩定")).toBeInTheDocument();
    expect(screen.getByText("今日未見記憶堆積，摘要與整理節奏正常。")).toBeInTheDocument();
  });
});
