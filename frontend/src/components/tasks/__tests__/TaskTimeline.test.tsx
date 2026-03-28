import TaskTimeline from "../TaskTimeline";
import { renderWithRouter, screen } from "../../../test/render";

describe("TaskTimeline", () => {
  it("renders source and target agent in timeline item", () => {
    renderWithRouter(
      <TaskTimeline
        items={[
          {
            id: "evt-1",
            type: "announce",
            sourceAgent: "Main",
            targetAgent: "Pandas",
            title: "發起跨會話消息",
            summary: "請回覆最新狀態與最大阻塞",
            timestamp: "1 小時前",
            status: "healthy",
            technicalDetails: "sessions_send",
          },
        ]}
      />,
    );

    expect(screen.getByText("發起跨會話消息")).toBeInTheDocument();
    expect(screen.getByText(/Main -> Pandas/)).toBeInTheDocument();
  });
});
