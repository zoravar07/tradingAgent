import type { LatestBriefingResponse } from "../types/briefing";
import type { DashboardResponse, PriceRange, PricesResponse } from "../types/dashboard";
import type {
  InsightsResponse,
  JournalEntry,
  JournalResponse,
  OrdersResponse,
  PerformanceResponse,
  PositionsResponse,
} from "../types/screens";

import { apiBase, isDesktopApp } from "./base";

export class ApiError extends Error {}

const UNREACHABLE = isDesktopApp()
  ? "Can't reach the Z Money backend. It should have started with the app — see ~/Library/Logs/Z Money/backend.log."
  : "Can't reach the Z Money API. Is it running? (.venv/bin/uvicorn api.server:app --reload --port 8000)";

async function getJson<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${await apiBase()}${path}`);
  } catch {
    throw new ApiError(UNREACHABLE);
  }
  if (!res.ok) {
    throw new ApiError(`API returned ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function fetchLatestBriefing(): Promise<LatestBriefingResponse> {
  return getJson<LatestBriefingResponse>("/briefing/latest");
}

export function fetchDashboard(): Promise<DashboardResponse> {
  return getJson<DashboardResponse>("/dashboard");
}

export function fetchPrices(ticker: string, range: PriceRange): Promise<PricesResponse> {
  return getJson<PricesResponse>(`/prices/${encodeURIComponent(ticker)}?range=${range}`);
}

export function fetchPositions(): Promise<PositionsResponse> {
  return getJson<PositionsResponse>("/positions");
}

export function fetchOrders(): Promise<OrdersResponse> {
  return getJson<OrdersResponse>("/orders");
}

export function fetchInsights(): Promise<InsightsResponse> {
  return getJson<InsightsResponse>("/insights");
}

export function fetchPerformance(): Promise<PerformanceResponse> {
  return getJson<PerformanceResponse>("/performance");
}

export function fetchJournal(): Promise<JournalResponse> {
  return getJson<JournalResponse>("/journal");
}

export async function createJournalEntry(body: {
  content: string;
  date?: string;
  linked_ticker?: string | null;
}): Promise<JournalEntry> {
  let res: Response;
  try {
    res = await fetch(`${await apiBase()}/journal`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(UNREACHABLE);
  }
  if (res.status === 422) {
    throw new ApiError("That note couldn't be saved — it needs some text.");
  }
  if (!res.ok) throw new ApiError(`API returned ${res.status} ${res.statusText}`);
  return res.json() as Promise<JournalEntry>;
}

export async function deleteJournalEntry(id: number): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${await apiBase()}/journal/${id}`, { method: "DELETE" });
  } catch {
    throw new ApiError(UNREACHABLE);
  }
  if (!res.ok) throw new ApiError(`API returned ${res.status} ${res.statusText}`);
}
