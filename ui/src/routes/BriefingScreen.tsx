import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise } from "@phosphor-icons/react";
import { ApiError, fetchLatestBriefing } from "../api/client";
import type { Briefing, LatestBriefingResponse } from "../types/briefing";
import { EmptyState } from "../components/EmptyState";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { StatusPill } from "../components/StatusPill";
import { fmtDateTime } from "../lib/format";
import { ActionsSection } from "../components/briefing/ActionsSection";
import { WatchingSection } from "../components/briefing/WatchingSection";
import { OvernightSection } from "../components/briefing/OvernightSection";
import { BookSection } from "../components/briefing/BookSection";
import { HealthSection } from "../components/briefing/HealthSection";
import { BlockedBanner, DriftBanner, UnresearchedBanner } from "../components/briefing/Banners";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; data: LatestBriefingResponse };

function runStatusTone(status: string): "gain" | "loss" | "risk" | "neutral" {
  if (status === "succeeded") return "gain";
  if (status === "blocked") return "risk";
  if (status === "failed") return "loss";
  return "neutral";
}

export function BriefingScreen() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      const data = await fetchLatestBriefing();
      setState({ kind: "loaded", data });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Unexpected error loading the briefing.";
      setState({ kind: "error", message });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-[var(--color-hairline)] px-8 py-5">
        <div>
          <h1 className="text-lg font-semibold text-[var(--color-ink)]">Briefing</h1>
          {state.kind === "loaded" && state.data.status === "ok" && (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <StatusPill tone={runStatusTone(state.data.run_status)}>{state.data.run_status}</StatusPill>
              {state.data.generated_at && (
                <span className="text-xs text-[var(--color-ink-faint)]">
                  generated {fmtDateTime(state.data.generated_at)}
                </span>
              )}
            </div>
          )}
        </div>
        <button
          onClick={load}
          disabled={state.kind === "loading"}
          className="flex shrink-0 items-center gap-1.5 rounded-md border border-[var(--color-hairline-strong)] px-3 py-1.5 text-xs font-medium text-[var(--color-ink-dim)] transition-colors hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)] active:scale-[0.98] disabled:opacity-50"
        >
          <ArrowClockwise size={13} className={state.kind === "loading" ? "animate-spin" : ""} />
          Refresh
        </button>
      </header>

      {state.kind === "loading" && <LoadingSkeleton />}
      {state.kind === "error" && <ErrorPanel message={state.message} onRetry={load} />}
      {state.kind === "loaded" && state.data.status === "no_runs_yet" && <EmptyState />}
      {state.kind === "loaded" && state.data.status === "ok" && (
        <BriefingContent briefing={state.data.briefing} />
      )}
    </div>
  );
}

function BriefingContent({ briefing }: { briefing: Briefing }) {
  return (
    <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-8 py-6">
      {briefing.blocked && <BlockedBanner blocked={briefing.blocked} />}
      {!briefing.blocked && briefing.unresearched_holdings.length > 0 && (
        <UnresearchedBanner holdings={briefing.unresearched_holdings} />
      )}
      {!briefing.blocked && briefing.drift_warning && <DriftBanner drift={briefing.drift_warning} />}

      {!briefing.blocked && (
        <>
          <ActionsSection actions={briefing.actions_today} />
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <WatchingSection watching={briefing.watching} />
            <OvernightSection changes={briefing.overnight_changes} />
          </div>
          <BookSection book={briefing.book} />
          <HealthSection health={briefing.portfolio_health} />
        </>
      )}
    </div>
  );
}
