import SettingsPage from "../SettingsPage";
import { renderWithRouter, screen } from "../../test/render";

describe("SettingsPage", () => {
  it("renders endpoint manager and mapping section", async () => {
    renderWithRouter(<SettingsPage />);

    expect(await screen.findByText("LLM Endpoint 管理")).toBeInTheDocument();
    expect(screen.getByText("新增 Endpoint")).toBeInTheDocument();
    expect(screen.getByText("Group / Level Mapping")).toBeInTheDocument();
  });
});
