import { Minus, TrendDown, TrendUp } from "@phosphor-icons/react";
import { PreviewBanner } from "../components/PreviewBanner";
import { StatusPill } from "../components/StatusPill";
import { ConvictionMeter } from "../components/ConvictionMeter";
import { SectionShell } from "../components/briefing/SectionShell";
import { SAMPLE_RESEARCH, type SampleMemo, type SampleResearchTicker } from "../lib/previewData";

const TREND_META = {
  strengthening: { tone: "gain" as const, icon: TrendUp, label: "Strengthening" },
  decaying: { tone: "loss" as const, icon: TrendDown, label: "Decaying" },
  steady: { tone: "neutral" as const, icon: Minus, label: "Steady" },
};

function CatalystTags({ text }: { text: string }) {
  const items = text
    .split(/,\s*/)
    .map((c) => c.replace(/\.$/, "").trim())
    .filter(Boolean);
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((c) => (
        <span key={c} className="rounded-md bg-[var(--color-accent-wash)] px-2 py-0.5 text-xs text-[var(--color-accent)]">
          {c}
        </span>
      ))}
    </div>
  );
}

function MemoCard({ memo }: { memo: SampleMemo }) {
  return (
    <div className="rounded-lg border border-[var(--color-hairline)] bg-[var(--color-panel-raised)] p-3.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-[var(--color-ink-faint)]">{memo.date}</span>
        <ConvictionMeter score={memo.conviction} size="sm" />
      </div>
      <div className="mt-2.5 flex flex-col gap-2 text-sm">
        <p className="text-[var(--color-ink)]">{memo.thesis}</p>
        <p className="text-[var(--color-ink-dim)]">
          <span className="font-medium text-[var(--color-loss)]">Bear case — </span>
          {memo.bearCase}
        </p>
        <CatalystTags text={memo.catalysts} />
      </div>
    </div>
  );
}

function TickerBlock({ ticker }: { ticker: SampleResearchTicker }) {
  const meta = TREND_META[ticker.trend];
  const [latest] = ticker.memos;

  return (
    <div className="border-b border-[var(--color-hairline)] py-5 first:pt-0 last:border-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-3">
        <span className="num text-lg font-bold text-[var(--color-ink)]">{ticker.ticker}</span>
        <StatusPill tone={meta.tone}>
          <meta.icon size={11} weight="bold" className="mr-1 inline" />
          {meta.label}
        </StatusPill>
        <span className="num ml-auto text-sm font-semibold text-[var(--color-ink)]">{latest.conviction}/100</span>
      </div>

      <div className="mt-3 flex flex-col gap-2.5 border-l border-[var(--color-hairline)] pl-4">
        {ticker.memos.map((memo) => (
          <MemoCard key={memo.date} memo={memo} />
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
          Not live yet — write-ups aren't saved between runs. This is what watching a thesis strengthen
          or decay over time will look like. Sample data shown.
        </PreviewBanner>

        <SectionShell
          title="Research archive"
          subtitle="Every past write-up per ticker, so you can see if the thesis is getting stronger or weaker."
          count={SAMPLE_RESEARCH.length}
        >
          {SAMPLE_RESEARCH.map((ticker) => (
            <TickerBlock key={ticker.ticker} ticker={ticker} />
          ))}
        </SectionShell>
      </div>
    </div>
  );
}
