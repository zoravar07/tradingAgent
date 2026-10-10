/**
 * Where the API lives. In the browser dev setup it is uvicorn on :8000. Inside
 * the desktop app the Tauri shell starts the backend itself — on 8000 if
 * free, otherwise a free port — and exposes the base URL through the
 * `api_base` command, so the page asks once and caches the answer.
 */
const DEFAULT_API_BASE = "http://localhost:8000/api";

declare global {
  interface Window {
    __TAURI__?: { core?: { invoke?: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> } };
  }
}

let resolved: Promise<string> | null = null;

export function apiBase(): Promise<string> {
  if (!resolved) {
    resolved = (async () => {
      const invoke = window.__TAURI__?.core?.invoke;
      if (invoke) {
        try {
          const base = await invoke("api_base");
          if (typeof base === "string" && base.length > 0) return base;
        } catch {
          // fall through to the default: the shell is present but the command failed
        }
      }
      return DEFAULT_API_BASE;
    })();
  }
  return resolved;
}

export const isDesktopApp = (): boolean => Boolean(window.__TAURI__);
