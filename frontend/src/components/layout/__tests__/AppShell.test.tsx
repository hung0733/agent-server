import App from "../../../App";
import { overviewPayload } from "../../../mock/dashboard";
import { renderWithRouter, screen } from "../../../test/render";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

describe("App shell", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(overviewPayload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the login gate before an API key is provided", () => {
    renderWithRouter(<App />);

    expect(screen.getByText("使用 API Key 登入控制台")).toBeInTheDocument();
    expect(screen.getByTestId("login-info-panel")).toBeInTheDocument();
    expect(screen.getByTestId("login-form-stack")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "主導覽" })).not.toBeInTheDocument();
  });

  it("renders primary navigation labels", async () => {
    window.sessionStorage.setItem("dashboard_api_key", "test-key");
    renderWithRouter(<App />);

    expect(await screen.findByRole("navigation", { name: "主導覽" })).toBeInTheDocument();
    expect(await screen.findByText("總覽")).toBeInTheDocument();
    expect(await screen.findByText("用量")).toBeInTheDocument();
    expect(await screen.findByText("Agents")).toBeInTheDocument();
  });

  it("shows the last updated label in zh-HK", async () => {
    window.sessionStorage.setItem("dashboard_api_key", "test-key");
    renderWithRouter(<App />);

    expect(await screen.findByText(/最後更新/)).toBeInTheDocument();
  });

  it("renders status rail content", async () => {
    window.sessionStorage.setItem("dashboard_api_key", "test-key");
    renderWithRouter(<App />);

    expect(await screen.findByText("當前狀態")).toBeInTheDocument();
  });

  it("switches shell language labels to english", async () => {
    const user = userEvent.setup();
    window.sessionStorage.setItem("dashboard_api_key", "test-key");
    renderWithRouter(<App />);

    await user.click(screen.getByRole("button", { name: "Switch to English" }));

    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    expect(screen.getByText(/Last updated/)).toBeInTheDocument();
    expect(screen.getByText("Current status")).toBeInTheDocument();
  });

  it("stores the api key and enters the dashboard after login", async () => {
    const user = userEvent.setup();
    renderWithRouter(<App />);

    await user.type(screen.getByLabelText("API Key"), "good-key");
    await user.click(screen.getByRole("button", { name: "登入" }));

    expect(window.sessionStorage.getItem("dashboard_api_key")).toBe("good-key");
    expect(screen.getByRole("navigation", { name: "主導覽" })).toBeInTheDocument();
  });

  it("shows a blocking loading state before dashboard data resolves", () => {
    window.sessionStorage.setItem("dashboard_api_key", "test-key");
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise(() => undefined) as Promise<Response>,
    );

    renderWithRouter(<App />);

    expect(screen.getByText("正在載入控制台...")).toBeInTheDocument();
    expect(screen.queryByText("推進順暢")).not.toBeInTheDocument();
  });

  it("returns to login when the dashboard API responds with unauthorized", async () => {
    window.sessionStorage.setItem("dashboard_api_key", "expired-key");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: "unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithRouter(<App />);

    expect(await screen.findByText("使用 API Key 登入控制台")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("dashboard_api_key")).toBeNull();
  });
});
