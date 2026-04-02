import { vi } from "vitest";
import { waitFor, screen } from "@testing-library/react";
import { renderWithRouter } from "../../test/render";
import MemoryPage from "../MemoryPage";
import { fetchSTM, fetchLTM } from "../../api/dashboard";

vi.mock("../../api/dashboard");

const mockSTMEntries = [
  {
    id: "checkpoint-001-bullet-1",
    kind: "stm" as const,
    agent: "Otter",
    timestamp: "2026-04-03T14:00:00Z",
    summary: "Alice 於 2025-11-15T14:30:00 提議...",
    sessionId: "session-test-123",
    sessionName: "session-test-123",
    status: "healthy" as const,
  },
];

const mockLTMEntries = [
  {
    id: "entry-001",
    kind: "ltm" as const,
    agent: "Pandas",
    timestamp: "2026-04-03T15:00:00Z",
    summary: "部署事故跟進已補寫長期記憶。",
    status: "healthy" as const,
  },
];

describe("MemoryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchSTM).mockResolvedValue({
      entries: mockSTMEntries,
      hasMore: false,
      source: "langgraph",
    });
    vi.mocked(fetchLTM).mockResolvedValue({
      entries: mockLTMEntries,
      hasMore: false,
      nextCursor: null,
      source: "qdrant",
    });
  });

  test("renders merged STM and LTM entries sorted by timestamp", async () => {
    renderWithRouter(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText("部署事故跟進已補寫長期記憶。")).toBeInTheDocument();
    });

    const entries = screen.getAllByRole("article");
    expect(entries[0]).toHaveTextContent("Pandas");
    expect(entries[1]).toHaveTextContent("Otter");
  });

  test("shows STM session name in timeline", async () => {
    renderWithRouter(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText("STM - session-test-123")).toBeInTheDocument();
    });
  });

  test("shows empty state when no entries", async () => {
    vi.mocked(fetchSTM).mockResolvedValue({
      entries: [],
      hasMore: false,
      source: "langgraph",
    });
    vi.mocked(fetchLTM).mockResolvedValue({
      entries: [],
      hasMore: false,
      nextCursor: null,
      source: "qdrant",
    });

    renderWithRouter(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText("最近記憶寫入穩定")).toBeInTheDocument();
    });
  });
});