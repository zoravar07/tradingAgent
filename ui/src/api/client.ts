import type { LatestBriefingResponse } from "../types/briefing";

// api/server.py runs on :8000 (uvicorn api.server:app --reload --port 8000),
// separate from Vite's dev server — CORS on the backend is scoped to Vite's
// origins for exactly this split-process local setup.
const API_BASE = "http://localhost:8000/api";

export class ApiError extends Error {}

export async function fetchLatestBriefing(): Promise<LatestBriefingResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/briefing/latest`);
  } catch {
    throw new ApiError(
      "Can't reach the Z Money API. Is it running? (.venv/bin/uvicorn api.server:app --reload --port 8000)",
    );
  }
  if (!res.ok) {
    throw new ApiError(`API returned ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<LatestBriefingResponse>;
}
