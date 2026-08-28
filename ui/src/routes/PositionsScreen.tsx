import { FileArrowUp, PencilSimple, UploadSimple } from "@phosphor-icons/react";
import { PreviewBanner } from "../components/PreviewBanner";
import { SectionShell } from "../components/briefing/SectionShell";
import { SAMPLE_POSITIONS } from "../lib/previewData";

const IMPORT_STEPS = [
  {
    icon: UploadSimple,
    title: "CSV import",
    body: "Download a Flex Query CSV from IBKR Client Portal and drag it in. Works on IBKR Lite — do this weekly.",
  },
  {
    icon: FileArrowUp,
    title: "Mark as filled",
    body: "When you place a proposed trade, click Filled and enter the price. Updates your book immediately.",
  },
  {
    icon: PencilSimple,
    title: "Manual entry",
    body: "Add or edit a position by hand — the fallback, and how your first positions will get loaded.",
  },
] as const;

export function PositionsScreen() {
  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-[var(--color-hairline)] px-8 py-5">
        <h1 className="text-lg font-semibold text-[var(--color-ink)]">Positions</h1>
      </header>

      <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-8 py-6">
        <PreviewBanner>
          Positions tracking isn't live yet — the API only serves the nightly briefing so far. This is
          what your book will look like once CSV imports and fills are wired up. Every row below is
          sample data, not a real position.
        </PreviewBanner>

        <SectionShell title="How positions get in" subtitle="Three ways, in order of preference.">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            {IMPORT_STEPS.map(({ icon: Icon, title, body }, i) => (
              <div key={title} className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-panel-raised)] text-xs font-semibold text-[var(--color-ink-dim)]">
                    {i + 1}
                  </span>
                  <Icon size={16} className="text-[var(--color-ink-faint)]" />
                  <span className="text-sm font-medium text-[var(--color-ink)]">{title}</span>
                </div>
                <p className="text-xs text-[var(--color-ink-dim)]">{body}</p>
              </div>
            ))}
          </div>
        </SectionShell>

        <SectionShell
          title="Your positions"
          subtitle="Every held position, reconciled against your last CSV import."
          count={SAMPLE_POSITIONS.length}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--color-hairline-strong)] text-left text-xs text-[var(--color-ink-faint)]">
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Ticker</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Qty</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Avg cost</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Opened</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Source</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Last verified</th>
                  <th className="pb-2 pr-4 font-medium whitespace-nowrap">Conviction @ entry</th>
                  <th className="pb-2 font-medium whitespace-nowrap">Peak since entry</th>
                </tr>
              </thead>
              <tbody>
                {SAMPLE_POSITIONS.map((p) => (
                  <tr key={p.ticker} className="border-b border-[var(--color-hairline)] last:border-0">
                    <td className="num py-2.5 pr-4 font-semibold text-[var(--color-ink)]">{p.ticker}</td>
                    <td className="num py-2.5 pr-4 text-[var(--color-ink-dim)]">{p.qty}</td>
                    <td className="num py-2.5 pr-4 text-[var(--color-ink-dim)]">${p.avgCost.toFixed(2)}</td>
                    <td className="py-2.5 pr-4 text-[var(--color-ink-dim)] whitespace-nowrap">{p.openedAt}</td>
                    <td className="py-2.5 pr-4 whitespace-nowrap text-[var(--color-ink-faint)]">{p.source}</td>
                    <td className="py-2.5 pr-4 text-[var(--color-ink-dim)] whitespace-nowrap">{p.lastVerifiedAt}</td>
                    <td className="num py-2.5 pr-4 text-[var(--color-ink-dim)]">{p.convictionAtEntry}</td>
                    <td className="num py-2.5 text-[var(--color-ink-dim)]">${p.peakSinceEntry.toFixed(2)}</td>
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
