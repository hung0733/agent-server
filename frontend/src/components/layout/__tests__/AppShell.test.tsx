import App from "../../../App";
import { renderWithRouter, screen } from "../../../test/render";
import userEvent from "@testing-library/user-event";

describe("App shell", () => {
  it("renders primary navigation labels", () => {
    renderWithRouter(<App />);

    expect(screen.getByRole("navigation", { name: "主導覽" })).toBeInTheDocument();
    expect(screen.getByText("總覽")).toBeInTheDocument();
    expect(screen.getByText("用量")).toBeInTheDocument();
    expect(screen.getByText("Agents")).toBeInTheDocument();
  });

  it("shows the last updated label in zh-HK", () => {
    renderWithRouter(<App />);

    expect(screen.getByText(/最後更新/)).toBeInTheDocument();
  });

  it("renders status rail content", () => {
    renderWithRouter(<App />);

    expect(screen.getByText("當前狀態")).toBeInTheDocument();
  });

  it("switches shell language labels to english", async () => {
    const user = userEvent.setup();
    renderWithRouter(<App />);

    await user.click(screen.getByRole("button", { name: "Switch to English" }));

    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(screen.getByText(/Last updated/)).toBeInTheDocument();
    expect(screen.getByText("Current status")).toBeInTheDocument();
  });
});
