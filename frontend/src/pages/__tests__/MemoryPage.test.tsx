import { renderWithRouter, screen } from "../../test/render";
import { MemoryPayload } from "../../types/dashboard";
import { vi } from "vitest";

import MemoryPage from "../MemoryPage";
import { useDashboardResource } from "../../hooks/useDashboardResource";

vi.mock("../../hooks/useDashboardResource", () => ({
  useDashboardResource: vi.fn(),
}));

const memoryFixture: MemoryPayload = {
  summary: {
    title: "記憶整理摘要",
    body: "摘要批次已恢復正常，待整理寫入維持低位。",
  },
  stats: [
    {
      title: "待整理片段",
      value: 12,
      note: "較昨日減少 3 項",
      status: "healthy",
    },
    {
      title: "最近 1 小時寫入",
      value: 28,
      note: "高峰期後回落",
      status: "warning",
    },
  ],
  recentEntries: [
    {
      id: "entry-1",
      title: "客戶升級要求",
      detail: "2 分鐘前完成摘要",
      timestamp: "2 分鐘前",
    },
    {
      id: "entry-2",
      title: "部署事故跟進",
      detail: "11 分鐘前補寫長期記憶",
      timestamp: "11 分鐘前",
    },
  ],
  source: "test",
};

describe("MemoryPage", () => {
  it("renders structured summary, stats, and recent entries", () => {
    vi.mocked(useDashboardResource).mockReturnValue({
      isLoading: false,
      resource: memoryFixture,
    });

    renderWithRouter(<MemoryPage />);

    expect(screen.getByText("記憶整理摘要")).toBeInTheDocument();
    expect(screen.getByText("摘要批次已恢復正常，待整理寫入維持低位。")).toBeInTheDocument();
    expect(screen.getByText("待整理片段")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("最近 1 小時寫入")).toBeInTheDocument();
    expect(screen.getByText("客戶升級要求")).toBeInTheDocument();
    expect(screen.getByText("部署事故跟進")).toBeInTheDocument();
  });

  it("renders fallback copy when stats and recent entries are empty", () => {
    vi.mocked(useDashboardResource).mockReturnValue({
      isLoading: false,
      resource: {
        ...memoryFixture,
        stats: [],
        recentEntries: [],
      },
    });

    renderWithRouter(<MemoryPage />);

    expect(screen.getAllByText("今日未見記憶堆積，摘要與整理節奏正常。")).toHaveLength(2);
  });
});
