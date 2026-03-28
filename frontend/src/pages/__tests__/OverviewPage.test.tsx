import OverviewPage from "../OverviewPage";
import App from "../../App";
import { renderWithRouter, screen } from "../../test/render";
import userEvent from "@testing-library/user-event";

describe("OverviewPage", () => {
  it("renders the hero conclusion and four KPI cards", () => {
    renderWithRouter(<OverviewPage />);

    expect(screen.getByText("今日總控")).toBeInTheDocument();
    expect(screen.getByText("待審批")).toBeInTheDocument();
    expect(screen.getByText("運行異常")).toBeInTheDocument();
    expect(screen.getByText("停滯任務")).toBeInTheDocument();
    expect(screen.getByText("預算風險")).toBeInTheDocument();
  });

  it("keeps high-priority right rail widgets visible", () => {
    renderWithRouter(<OverviewPage />);

    expect(screen.getByText("今日用量")).toBeInTheDocument();
    expect(screen.getByText("活躍 Agents")).toBeInTheDocument();
  });

  it("navigates to usage and memory sections", async () => {
    const user = userEvent.setup();
    renderWithRouter(<App />);

    await user.click(screen.getByText("用量"));
    expect(screen.getByText("定時任務用量佔比")).toBeInTheDocument();

    await user.click(screen.getByText("記憶"));
    expect(screen.getByText("長期記憶健康")).toBeInTheDocument();
  });

  it("renders the usage chart as a labelled image with data-driven legend", async () => {
    const user = userEvent.setup();
    renderWithRouter(<App />);

    await user.click(screen.getByText("用量"));

    expect(screen.getByRole("img", { name: "定時任務用量圖表" })).toBeInTheDocument();
    expect(screen.getByText("x-radar-collect")).toBeInTheDocument();
    expect(screen.getByText("16.58%")).toBeInTheDocument();
  });
});
