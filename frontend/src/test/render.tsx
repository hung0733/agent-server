import { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import i18n from "../i18n";
import "../i18n";

export function renderWithRouter(ui: ReactElement) {
  void i18n.changeLanguage("zh-HK");
  return render(
    <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      {ui}
    </MemoryRouter>,
  );
}

export * from "@testing-library/react";
