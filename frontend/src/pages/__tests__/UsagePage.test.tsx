import UsagePage from "../UsagePage";
import { renderWithRouter, screen } from "../../test/render";

describe("UsagePage", () => {
  it("renders today token and cost summary cards", async () => {
    renderWithRouter(<UsagePage />);

    expect(await screen.findByText("今日 Tokens")).toBeInTheDocument();
    expect(screen.getByText("1,509,786")).toBeInTheDocument();
    expect(screen.getByText("今日成本")).toBeInTheDocument();
    expect(screen.getByText("US$0.81")).toBeInTheDocument();
  });
});
