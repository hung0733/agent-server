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

  it("renders optional task context when group and message snippet are present", () => {
    renderWithRouter(
      <TaskTimeline
        items={[
          {
            id: "evt-2",
            type: "reply",
            sourceAgent: "Pandas",
            targetAgent: "Main",
            title: "通過既有會話回信",
            summary: "目前缺的不是任務，而是可審查輸入。",
            timestamp: "58 分鐘前",
            status: "warning",
            technicalDetails: "announce_step",
            group: "內容審批",
            messageSnippet: "等緊新一批可審查內容先可以繼續。",
          },
        ]}
      />,
    );

    expect(screen.getByText("內容審批")).toHaveClass("timeline-item__group");
    expect(screen.getByText("等緊新一批可審查內容先可以繼續。")).toHaveClass(
      "timeline-item__snippet",
    );
  });

  it("renders an empty state when there are no timeline items", () => {
    renderWithRouter(<TaskTimeline items={[]} />);

    expect(screen.getByText("最近未見跨會話活動")).toBeInTheDocument();
    expect(screen.getByText("目前未有可顯示的排程、任務或協作事件。")).toBeInTheDocument();
  });
});
