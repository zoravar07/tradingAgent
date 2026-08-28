import { FileArrowUp, PencilSimple, UploadSimple, WarningCircle } from "@phosphor-icons/react";
import { PreviewBanner } from "../components/PreviewBanner";
import { StatusPill } from "../components/StatusPill";
import { ConvictionMeter } from "../components/ConvictionMeter";
import { SectionShell } from "../components/briefing/SectionShell";
import { fmtPct, fmtUsd, fmtUsd2 } from "../lib/format";
import { SAMPLE_POSITIONS, type SamplePosition } from "../lib/previewData";

const IMPORT_STEPS = [
  { icon: UploadSimple, title: "CSV import", body: "Drag in a Flex Query CSV from IBKR. Works on Lite — do this weekly." },
  { icon: FileArrowUp, title: "Mark as filled", body: "Place a proposed trade, click Filled, enter the price." },
  { icon: PencilSimple, title: "Manual entry", body: "Add or edit a position by hand — the fallback." },
] as const;

function PositionCard({ p }: { p: SamplePosition }) {
  const pnlPct = ((p.currentPrice - p.avgCost) / p.avgCost) * 100;
  const isGain = pnlPct >= 0;

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-[var(--color-hairline)] bg-[var(--color-panel)] p-4 transition-colors hover:border-[var(--color-hairline-strong)]">
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="num text-lg font-bold text-[var(--color-ink)]">{p.ticker}</span>
          <p className="num text-xs text-[var(--color-ink-faint)]">{p.qty} sh · avg {fmtUsd2(p.avgCost)}</p>
        </div>
        <StatusPill tone={isGain ? "gain" : "loss"}>{fmtPct(pnlPct)}</StatusPill>
      </div>

      <div>
        <p className="num text-2xl font-semibold text-[var(--color-ink)]">{fmtUsd(p.qty * p.currentPrice)}</p>
        <p className="num text-xs text-[var(--color-ink-faint)]">at {fmtUsd2(p.currentPrice)}/sh</p>
      </div>

      <ConvictionMeter score={p.convictionNow} size="sm" />

      {p.alert && (
        <div className="flex items-center gap-1.5 rounded-md bg-[var(--color-risk-wash)] px-2 py-1.5 text-xs font-medium text-[var(--color-risk)]">
          <WarningCircle size={13} weight="fill" />
          {p.alert}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-[var(--color-hairline)] pt-2.5 text-xs text-[var(--color-ink-faint)]">
        <span>Opened {p.openedAt}</span>
        <span>·</span>
        <span>{p.source}</span>
      </div>
    </div>
  );
}

export function PositionsScreen() {
  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-[var(--color-hairline)] px-8 py-5">
        <h1 className="text-lg font-semibold text-[var(--color-ink)]">Positions</h1>
      </header>

      <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-8 py-6">
        <PreviewBanner>
          Not live yet — this is a preview of what your book will look like. Every card below is sample
          data.
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

        <div>
          <div className="mb-3 flex items-baseline gap-2">
            <h2 className="text-[13px] font-semibold tracking-[0.02em] text-[var(--color-ink)]">Your positions</h2>
            <span className="text-[13px] text-[var(--color-ink-faint)]">{SAMPLE_POSITIONS.length}</span>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {SAMPLE_POSITIONS.map((p) => (
              <PositionCard key={p.ticker} p={p} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
