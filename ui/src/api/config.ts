import type { ConfigResponse, EditableConfig, ValidationErrorItem } from "../types/settings";
import { ApiError } from "./client";

import { apiBase } from "./base";

export type ConfigSubmitResult =
  | { ok: true; data: ConfigResponse }
  | { ok: false; errors: ValidationErrorItem[] };

export async function fetchConfig(): Promise<ConfigResponse> {
  let res: Response;
  try {
    res = await fetch(`${await apiBase()}/config`);
  } catch {
    throw new ApiError("Can't reach the Z Money API. Is it running?");
  }
  if (!res.ok) throw new ApiError(`API returned ${res.status} ${res.statusText}`);
  return res.json() as Promise<ConfigResponse>;
}

async function submit(path: string, body?: EditableConfig): Promise<ConfigSubmitResult> {
  let res: Response;
  try {
    res = await fetch(`${await apiBase()}${path}`, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Can't reach the Z Money API. Is it running?");
  }

  if (res.status === 422) {
    const payload = await res.json();
    return { ok: false, errors: payload.detail as ValidationErrorItem[] };
  }
  if (!res.ok) throw new ApiError(`API returned ${res.status} ${res.statusText}`);
  return { ok: true, data: (await res.json()) as ConfigResponse };
}

export function updateConfig(body: EditableConfig): Promise<ConfigSubmitResult> {
  return submit("/config/update", body);
}

export function resetConfigToDefaults(): Promise<ConfigSubmitResult> {
  return submit("/config/reset");
}

/** loc looks like ["body", "risk", "max_position_pct"] — drop the leading
 * "body" segment and join the rest into a dotted field key matching the
 * form's own field ids. */
export function fieldKeyFromLoc(loc: (string | number)[]): string {
  return loc.filter((seg) => seg !== "body").join(".");
}
