import { describe, it, expect, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import AgentTab from "../AgentTab";
import { renderWithRouter, screen, within } from "../../../test/render";

vi.mock("../../../api/dashboard", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/dashboard")>();
  return {
    ...actual,
    createAgent: vi.fn().mockResolvedValue({
      agent: {
        id: "new-agent",
        name: "New Agent",
        role: "",
        status: "healthy",
        currentTask: "",
        latestOutput: "",
        scheduled: false,
        isActive: true,
        isSubAgent: false,
        phoneNo: null,
        whatsappKey: null,
        agentTypeId: "type-research",
        agentTypeName: "研究型員工",
      },
    }),
    updateAgent: vi.fn().mockResolvedValue({
      agent: {
        id: "main",
        name: "main",
        role: "主控與協調",
        status: "healthy",
        currentTask: "creators-sales-lead-radar",
        latestOutput: "完成第一輪審查摘要",
        scheduled: true,
        isActive: false,
        isSubAgent: false,
        phoneNo: null,
        whatsappKey: null,
        agentTypeId: "type-research",
        agentTypeName: "研究型員工",
      },
    }),
  };
});

describe("AgentTab", () => {
  it("renders agent cards and add button", async () => {
    renderWithRouter(<AgentTab />);

    expect(await screen.findByRole("button", { name: "新增員工" })).toBeInTheDocument();
    expect(screen.getByText("main")).toBeInTheDocument();
    expect(screen.getByText("otter")).toBeInTheDocument();
    expect(screen.getByText("pandas")).toBeInTheDocument();
  });

  it("shows 停用 badge for inactive agents", async () => {
    renderWithRouter(<AgentTab />);
    await screen.findByText("main");
    expect(screen.getByText("停用")).toBeInTheDocument();
  });

  it("shows Sub badge for sub agents", async () => {
    renderWithRouter(<AgentTab />);
    await screen.findByText("otter");
    expect(screen.getByText("Sub")).toBeInTheDocument();
  });

  it("opens create modal when add button is clicked", async () => {
    const user = userEvent.setup();
    renderWithRouter(<AgentTab />);

    await user.click(await screen.findByRole("button", { name: "新增員工" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByRole("heading", { name: "新增員工" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("員工名稱")).toBeInTheDocument();
  });

  it("shows validation error when submitting without name", async () => {
    const user = userEvent.setup();
    renderWithRouter(<AgentTab />);

    await user.click(await screen.findByRole("button", { name: "新增員工" }));
    await user.click(screen.getByRole("button", { name: "儲存" }));

    expect(await screen.findByText("名稱為必填。")).toBeInTheDocument();
  });

  it("shows validation error when submitting without agent type", async () => {
    const user = userEvent.setup();
    renderWithRouter(<AgentTab />);

    await user.click(await screen.findByRole("button", { name: "新增員工" }));
    await user.type(screen.getByPlaceholderText("員工名稱"), "New Agent");
    await user.click(screen.getByRole("button", { name: "儲存" }));

    expect(await screen.findByText("員工類型為必填。")).toBeInTheDocument();
  });

  it("opens edit modal pre-filled when edit button is clicked", async () => {
    const user = userEvent.setup();
    renderWithRouter(<AgentTab />);

    await screen.findByText("main");
    const mainCard = screen.getByText("main").closest("article")!;
    await user.click(within(mainCard).getByRole("button", { name: "編輯" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("編輯員工")).toBeInTheDocument();
    expect(screen.getByDisplayValue("main")).toBeInTheDocument();
  });

  it("closes modal when cancel is clicked", async () => {
    const user = userEvent.setup();
    renderWithRouter(<AgentTab />);

    await user.click(await screen.findByRole("button", { name: "新增員工" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
