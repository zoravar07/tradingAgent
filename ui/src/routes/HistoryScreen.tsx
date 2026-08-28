import { FunnelSimple, Moon, Prohibit, WarningOctagon } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import { PreviewBanner } from "../components/PreviewBanner";
import { StatusPill } from "../components/StatusPill";
import { fmtUsd2 } from "../lib/format";
import { SAMPLE_TIMELINE, type SampleProposal, type SampleRunEvent, type TimelineEntry } from "../lib/previewData";

const DISABLED_FILTERS = ["Ticker", "Status", "Date range"];

const PROPOSAL_STATUS_META = {
  filled: { tone: "gain" as const, label: "Filled" },
  dismissed: { tone: "neutral" as const, label: "Dismissed" },
  open: { tone: "accent" as const, label: "Open" },
};

const RUN_EVENT_META: Record<SampleRunEvent["status"], { tone: "loss" | "neutral"; icon: Icon; label: string }> = {
  blocked: { tone: "loss", icon: Prohibit, label: "Blocked" },
  failed: { tone: "loss", icon: WarningOctagon, label: "Failed" },
  quiet: { tone: "neutral", icon: Moon, label: "Quiet run" },
};

function ProposalCard({ p }: { p: SampleProposal }) {
  const status = PROPOSAL_STATUS_META[p.status];
  const resultTone = p.result?.startsWith("-") ? "text-[var(--color-loss)]" : "text-[var(--color-gain)]";
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-panel)] px-3.5 py-2.5">
      <StatusPill tone={p.action === "BUY" ? "gain" : "loss"}>
        {p.action}
        {p.isTrim ? " · trim" : ""}
      </StatusPill>
      <span className="num text-sm font-semibold text-[var(--color-ink)]">{p.ticker}</span>
      <span className="num text-xs text-[var(--color-ink-faint)]">
        {p.qty} sh{p.fillPrice ? ` @ ${fmtUsd2(p.fillPrice)}` : ""}
      </span>
      <StatusPill tone={status.tone}>{status.label}</StatusPill>
      {p.result && <span className={`num ml-auto text-sm font-medium ${resultTone}`}>{p.result}</span>}
    </div>
  );
}

function RunEventCard({ e }: { e: SampleRunEvent }) {
  const meta = RUN_EVENT_META[e.status];
  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-[var(--color-hairline)] bg-[var(--color-panel)] px-3.5 py-2.5">
      <meta.icon size={14} className="shrink-0 text-[var(--color-ink-faint)]" />
      <StatusPill tone={meta.tone}>{meta.label}</StatusPill>
      <span className="text-xs text-[var(--color-ink-faint)]">{e.note}</span>
    </div>
  );
}

function groupByDate(entries: TimelineEntry[]): [string, TimelineEntry[]][] {
  const groups: [string, TimelineEntry[]][] = [];
  for (const entry of entries) {
    const last = groups[groups.length - 1];
    if (last && last[0] === entry.date) {
      last[1].push(entry);
    } else {
      groups.push([entry.date, [entry]]);
    }
  }
  return groups;
}

export function HistoryScreen() {
  const groups = groupByDate(SAMPLE_TIMELINE);

  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-[var(--color-hairline)] px-8 py-5">
        <h1 className="text-lg font-semibold text-[var(--color-ink)]">History</h1>
      </header>

      <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-8 py-6">
        <PreviewBanner>
          Not saved yet — only the latest run persists today. This is what a full timeline of every
          trade proposed, filled, and dismissed will look like. Sample data shown.
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

        <div className="flex flex-col">
          {groups.map(([date, entries], i) => (
            <div key={date} className="flex gap-4">
              <div className="flex flex-col items-center">
                <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full bg-[var(--color-accent)]" />
                {i < groups.length - 1 && <span className="w-px flex-1 bg-[var(--color-hairline)]" />}
              </div>
              <div className="flex-1 pb-6">
                <p className="text-xs font-medium text-[var(--color-ink-faint)]">{date}</p>
                <div className="mt-2 flex flex-col gap-2">
                  {entries.map((entry, j) =>
                    entry.kind === "proposal" ? (
                      <ProposalCard key={j} p={entry} />
                    ) : (
                      <RunEventCard key={j} e={entry} />
                    ),
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
