import OverviewPage from "../OverviewPage";
import App from "../../App";
import { renderWithRouter, screen } from "../../test/render";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { overviewPayload } from "../../mock/dashboard";

describe("OverviewPage", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the hero conclusion and four KPI cards", async () => {
    renderWithRouter(<OverviewPage />);

    expect(await screen.findByText("今日總控")).toBeInTheDocument();
    expect(await screen.findByText("待審批")).toBeInTheDocument();
    expect(await screen.findByText("運行異常")).toBeInTheDocument();
    expect(await screen.findByText("停滯任務")).toBeInTheDocument();
    expect(await screen.findByText("預算風險")).toBeInTheDocument();
  });

  it("keeps high-priority right rail widgets visible", async () => {
    renderWithRouter(<OverviewPage />);

    expect(await screen.findByText("今日用量")).toBeInTheDocument();
    expect(await screen.findByText("活躍 Agents")).toBeInTheDocument();
  });

  it("navigates to usage and memory sections", async () => {
    const user = userEvent.setup();
    window.sessionStorage.setItem("dashboard_api_key", "test-key");
    renderWithRouter(<App />);

    await user.click(screen.getByText("用量"));
    expect(screen.getByText("定時任務用量佔比")).toBeInTheDocument();

    await user.click(screen.getByText("記憶"));
    expect(screen.getByText("長期記憶健康")).toBeInTheDocument();
  });

  it("renders the usage chart as a labelled image with data-driven legend", async () => {
    const user = userEvent.setup();
    window.sessionStorage.setItem("dashboard_api_key", "test-key");
    renderWithRouter(<App />);

    await user.click(screen.getByText("用量"));

    expect(screen.getByRole("img", { name: "定時任務用量圖表" })).toBeInTheDocument();
    expect(screen.getByText("x-radar-collect")).toBeInTheDocument();
    expect(screen.getByText("16.58%")).toBeInTheDocument();
  });

  it("shows a blocking loading state before usage data resolves", async () => {
    const user = userEvent.setup();
    window.sessionStorage.setItem("dashboard_api_key", "test-key");

    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
      if (url.includes("/api/dashboard/usage")) {
        return new Promise(() => undefined) as Promise<Response>;
      }

      return Promise.resolve(
        new Response(JSON.stringify(overviewPayload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithRouter(<App />);
    await user.click(await screen.findByText("用量"));

    expect(screen.getByText("正在載入控制台...")).toBeInTheDocument();
    expect(screen.queryByText("定時任務用量佔比")).not.toBeInTheDocument();
  });
});
