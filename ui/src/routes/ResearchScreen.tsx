import { Minus, TrendDown, TrendUp } from "@phosphor-icons/react";
import { PreviewBanner } from "../components/PreviewBanner";
import { StatusPill } from "../components/StatusPill";
import { SectionShell } from "../components/briefing/SectionShell";
import { SAMPLE_RESEARCH, type SampleResearchTicker } from "../lib/previewData";

const TREND_META = {
  strengthening: { tone: "gain" as const, icon: TrendUp, label: "Strengthening" },
  decaying: { tone: "loss" as const, icon: TrendDown, label: "Decaying" },
  steady: { tone: "neutral" as const, icon: Minus, label: "Steady" },
};

function TickerMemos({ ticker }: { ticker: SampleResearchTicker }) {
  const meta = TREND_META[ticker.trend];
  const [latest] = ticker.memos;
  return (
    <div className="border-b border-[var(--color-hairline)] py-5 first:pt-0 last:border-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-3">
        <span className="num text-base font-semibold text-[var(--color-ink)]">{ticker.ticker}</span>
        <StatusPill tone={meta.tone}>
          <meta.icon size={11} weight="bold" className="mr-1 inline" />
          {meta.label}
        </StatusPill>
        <span className="num ml-auto text-sm text-[var(--color-ink-dim)]">conviction {latest.conviction}</span>
      </div>

      <div className="mt-3 flex flex-col gap-3 border-l border-[var(--color-hairline)] pl-4">
        {ticker.memos.map((memo) => (
          <div key={memo.date}>
            <div className="flex items-baseline gap-2 text-xs text-[var(--color-ink-faint)]">
              <span>{memo.date}</span>
              <span className="num text-[var(--color-ink-dim)]">conviction {memo.conviction}</span>
            </div>
            <p className="mt-0.5 text-sm text-[var(--color-ink-dim)]">{memo.note}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ResearchScreen() {
  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-[var(--color-hairline)] px-8 py-5">
        <h1 className="text-lg font-semibold text-[var(--color-ink)]">Research</h1>
      </header>

      <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-8 py-6">
        <PreviewBanner>
          Research memos aren't stored here yet. Once run history is persisted, every write-up the
          research agent produces per ticker will show up below, so you can see a thesis strengthen or
          decay over time. Sample data shown.
        </PreviewBanner>

        <SectionShell
          title="Research archive"
          subtitle="Every past write-up per ticker, so you can see if the thesis is getting stronger or weaker."
          count={SAMPLE_RESEARCH.length}
        >
          {SAMPLE_RESEARCH.map((ticker) => (
            <TickerMemos key={ticker.ticker} ticker={ticker} />
          ))}
        </SectionShell>
      </div>
    </div>
  );
}
