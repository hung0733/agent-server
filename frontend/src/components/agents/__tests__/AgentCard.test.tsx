import AgentCard from "../AgentCard";
import { renderWithRouter, screen } from "../../../test/render";

describe("AgentCard", () => {
  it("renders agent role, status, and latest output", () => {
    renderWithRouter(
      <AgentCard
        agent={{
          id: "main",
          name: "main",
          role: "主控與協調",
          status: "healthy",
          currentTask: "creators-sales-lead-radar",
          latestOutput: "完成第一輪審查摘要",
          scheduled: true,
          isActive: true,
          isSubAgent: false,
          phoneNo: null,
          whatsappKey: null,
          agentTypeId: null,
          agentTypeName: null,
        }}
      />,
    );

    expect(screen.getByText("主控與協調")).toBeInTheDocument();
    expect(screen.getByText("完成第一輪審查摘要")).toBeInTheDocument();
  });
});
