import { createContext, useContext } from "react";

import { OverviewPayload } from "../types/dashboard";

export const DashboardOverviewContext = createContext<OverviewPayload | null>(null);

export function useDashboardOverview(): OverviewPayload | null {
  return useContext(DashboardOverviewContext);
}
