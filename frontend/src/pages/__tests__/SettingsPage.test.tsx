import SettingsPage from "../SettingsPage";
import { renderWithRouter, screen } from "../../test/render";

describe("SettingsPage", () => {
  it("renders a compact endpoint form without redundant create button", async () => {
    renderWithRouter(<SettingsPage />);

    expect(await screen.findByText("LLM Endpoint 管理")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "建立 Endpoint" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新增 Endpoint" })).not.toBeInTheDocument();
    expect(screen.getByText("Group / Level Mapping")).toBeInTheDocument();
  });
});
