import userEvent from "@testing-library/user-event";

import AgentsPage from "../AgentsPage";
import { renderWithRouter, screen, within } from "../../test/render";

describe("AgentsPage", () => {
  it("renders a single-agent detail editor in the tools tab", async () => {
    const user = userEvent.setup();
    renderWithRouter(<AgentsPage />);

    expect(await screen.findByRole("tab", { name: "員工" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "員工類型" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "排程" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "員工工具" })).toBeInTheDocument();

    expect(screen.getByText("main")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "員工工具" }));

    expect(await screen.findByRole("heading", { name: "main" })).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "otter" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "otter" }));

    expect(await screen.findByRole("heading", { name: "otter" })).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.getAllByText("繼承自類型")).toHaveLength(2);
  });

  it("renders agent type table in the agent-type tab", async () => {
    const user = userEvent.setup();
    renderWithRouter(<AgentsPage />);

    await user.click(await screen.findByRole("tab", { name: "員工類型" }));

    expect(await screen.findByRole("button", { name: "新增員工類型" })).toBeInTheDocument();
    expect(screen.getByText("研究型員工")).toBeInTheDocument();
    expect(screen.getByText("助理型員工")).toBeInTheDocument();
  });

  it("renders method and message schedule sections in the schedule tab", async () => {
    const user = userEvent.setup();
    renderWithRouter(<AgentsPage />);

    await user.click(await screen.findByRole("tab", { name: "排程" }));

    const headings = await screen.findAllByRole("heading", { level: 3 });

    expect(headings[0]).toHaveTextContent("Message Schedules");
    expect(headings[1]).toHaveTextContent("Method Schedules");
    expect(screen.getByRole("button", { name: "新增排程" })).toBeInTheDocument();
    expect(screen.getByText("Daily review")).toBeInTheDocument();
    expect(screen.getByText("Morning ping")).toBeInTheDocument();
  });

  it("shows the inline message schedule form", async () => {
    const user = userEvent.setup();
    renderWithRouter(<AgentsPage />);

    await user.click(await screen.findByRole("tab", { name: "排程" }));
    await user.click(await screen.findByRole("button", { name: "新增排程" }));

    expect(await screen.findByRole("heading", { name: "新增 message 排程" })).toBeInTheDocument();
    expect(screen.getByLabelText("名稱")).toBeInTheDocument();
    expect(screen.getByLabelText("Prompt")).toBeInTheDocument();
    expect(screen.getByLabelText("執行員工")).toBeInTheDocument();
  });
});
