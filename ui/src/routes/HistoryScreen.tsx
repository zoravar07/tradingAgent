import { FunnelSimple } from "@phosphor-icons/react";
import { PreviewBanner } from "../components/PreviewBanner";
import { StatusPill } from "../components/StatusPill";
import { SectionShell } from "../components/briefing/SectionShell";
import { SAMPLE_RUNS } from "../lib/previewData";

function runTone(status: (typeof SAMPLE_RUNS)[number]["status"]): "gain" | "loss" {
  return status === "succeeded" ? "gain" : "loss";
}

const DISABLED_FILTERS = ["Ticker", "Status", "Date range"];

export function HistoryScreen() {
  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-[var(--color-hairline)] px-8 py-5">
        <h1 className="text-lg font-semibold text-[var(--color-ink)]">History</h1>
      </header>

      <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-8 py-6">
        <PreviewBanner>
          Run history isn't persisted yet — the database only tracks the latest briefing right now. Once
          every run's proposals and fills are stored, this table fills in for real and becomes
          filterable. Sample data shown.
        </PreviewBanner>

        <div className="flex flex-wrap items-center gap-2">
          {DISABLED_FILTERS.map((label) => (
            <span
              key={label}
              className="flex cursor-not-allowed items-center gap-1.5 rounded-md border border-[var(--color-hairline)] px-3 py-1.5 text-xs font-medium text-[var(--color-ink-faint)]"
            >
              <FunnelSimple size={12} />
              {label}
            </span>
          ))}
          <span className="text-xs text-[var(--color-ink-faint)]">Filtering isn't wired up yet.</span>
        </div>

        <SectionShell
          title="Run history"
          subtitle="Every nightly run and what happened to its proposals."
          count={SAMPLE_RUNS.length}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--color-hairline-strong)] text-left text-xs text-[var(--color-ink-faint)]">
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Run</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Status</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Proposals</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Filled</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Dismissed</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Open</th>
                  <th className="pb-2 font-medium whitespace-nowrap">Notes</th>
                </tr>
              </thead>
              <tbody>
                {SAMPLE_RUNS.map((run) => (
                  <tr key={run.date} className="border-b border-[var(--color-hairline)] last:border-0">
                    <td className="num py-2.5 pr-4 whitespace-nowrap text-[var(--color-ink)]">{run.date}</td>
                    <td className="py-2.5 pr-4">
                      <StatusPill tone={runTone(run.status)}>{run.status}</StatusPill>
                    </td>
                    <td className="num py-2.5 pr-4 text-[var(--color-ink-dim)]">{run.proposals}</td>
                    <td className="num py-2.5 pr-4 text-[var(--color-ink-dim)]">{run.filled}</td>
                    <td className="num py-2.5 pr-4 text-[var(--color-ink-dim)]">{run.dismissed}</td>
                    <td className="num py-2.5 pr-4 text-[var(--color-ink-dim)]">{run.open}</td>
                    <td className="py-2.5 text-[var(--color-ink-faint)]">{run.note ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionShell>
      </div>
    </div>
  );
}
