import { ArrowClockwise, Lightbulb, Minus, TrendDown, TrendUp } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import { fetchInsights } from "../api/client";
import type { InsightTicker, Memo, Trend } from "../types/screens";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { fmtDate, fmtPct, fmtPctPlain } from "../lib/format";
import { GLOSSARY } from "../lib/glossary";
import { humanizeKey } from "../lib/humanize";
import { companyName } from "../lib/tickers";
import { useAsyncData } from "../lib/useAsyncData";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardFooter, CardHeader } from "../components/ui/Card";
import { ConvictionBar, ConvictionScore } from "../components/ui/ConvictionScore";
import { DetailBlock, Disclosure } from "../components/ui/Disclosure";
import { EmptyRow, ScreenShell, Section } from "../components/ui/ScreenShell";
import { StatusPill, Tag } from "../components/ui/StatusPill";
import { Term } from "../components/ui/Term";

/** Each research factor in plain words, with what the score is judging. */
const FACTOR_GLOSS: Record<string, { label: string; meaning: string }> = {
  business_quality: { label: "How good the business is", meaning: "Does it earn a high return on the money it invests, and can it keep its prices up?" },
  financial_health: { label: "Financial health", meaning: "Growth, how much of its profit turns into cash, and how much debt it carries." },
  whats_priced_in: { label: "What the price already assumes", meaning: "How fast the company would need to grow to justify today's share price." },
  variant_perception: { label: "Where we differ from the crowd", meaning: "Is there a reason to think the market has this one wrong?" },
  earnings_quality: { label: "Quality of recent results", meaning: "Did it beat or miss forecasts, and were the profits real cash?" },
  catalyst_path: { label: "What could move the price", meaning: "Specific upcoming events that could change the share price, and when." },
  downside_asymmetry: { label: "How bad the bad case is", meaning: "How much could be lost if the bear case plays out, regardless of how likely it is." },
  ownership_flow: { label: "Who is buying and selling", meaning: "Big funds' holdings over several quarters and insiders' own trades." },
  analyst_signals: { label: "Analyst signals", meaning: "Rating changes, price-target moves and the direction of forecast revisions." },
  news_sentiment: { label: "News", meaning: "How much news there is, its tone, and whether any of it changes the case." },
  technical_momentum: { label: "Price trend", meaning: "Where the price sits against its recent averages, and how it has moved against the market." },
};

const TREND_META: Record<Trend, { tone: "gain" | "loss" | "neutral"; icon: Icon; label: string }> = {
  strengthening: { tone: "gain", icon: TrendUp, label: "Case getting stronger" },
  decaying: { tone: "loss", icon: TrendDown, label: "Case getting weaker" },
  steady: { tone: "neutral", icon: Minus, label: "Unchanged" },
  new: { tone: "neutral", icon: Minus, label: "First write-up" },
};

/** The factor scores behind a conviction number, as a small ranked bar list. */
function Subscores({ subscores }: { subscores: Record<string, number> }) {
  const entries = Object.entries(subscores).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return null;
  return (
    <ul className="grid grid-cols-1 gap-x-sp-6 gap-y-sp-3 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <li key={key} className="flex items-center gap-sp-3">
          <span className="w-52 shrink-0 t-meta text-ink-dim">
            {FACTOR_GLOSS[key] ? <Term text={FACTOR_GLOSS[key].label} definition={FACTOR_GLOSS[key].meaning} /> : humanizeKey(key)}
          </span>
          <ConvictionBar score={value} className="flex-1" />
        </li>
      ))}
    </ul>
  );
}

function LatestMemo({ memo }: { memo: Memo }) {
  return (
    <div className="flex flex-col gap-sp-5">
      <DetailBlock label="Where we differ from the crowd">{memo.variant_view}</DetailBlock>
      <DetailBlock label="What most investors think">{memo.consensus_view}</DetailBlock>
      <DetailBlock label="The case for owning it" define={GLOSSARY.thesis}>{memo.thesis_summary}</DetailBlock>
      {memo.bear_case && (
        <DetailBlock label="What could go wrong" tone="loss" define={GLOSSARY.bearCase}>
          {memo.bear_case}
          {memo.estimated_downside_pct !== null && (
            <p className="mt-sp-2 t-body">
              If it does, the estimate is a fall of about{" "}
              <span className="num-table font-semibold text-loss">
                {fmtPctPlain(memo.estimated_downside_pct)}
              </span>
            </p>
          )}
        </DetailBlock>
      )}
      {memo.catalysts.length > 0 && (
        <DetailBlock label="What could move the price">
          <ul className="flex flex-col gap-sp-2">
            {memo.catalysts.map((c, i) => (
              <li key={i} className="flex gap-sp-3">
                <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-ink-faint" aria-hidden />
                <span>
                  {c.description}
                  {c.expected_date && (
                    <span className="text-ink-faint"> — expected {c.expected_date}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </DetailBlock>
      )}
      {memo.risks.length > 0 && (
        <DetailBlock label="Risks to watch">
          <ul className="flex flex-col gap-sp-2">
            {memo.risks.map((r, i) => (
              <li key={i} className="flex gap-sp-3">
                <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-ink-faint" aria-hidden />
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </DetailBlock>
      )}
      <DetailBlock label="How the score was built">
        <Subscores subscores={memo.subscores} />
        {memo.unavailable_factors.length > 0 && (
          <p className="mt-sp-4 t-meta text-ink-faint">
            No evidence was available for: {memo.unavailable_factors.map((k) => FACTOR_GLOSS[k]?.label ?? humanizeKey(k)).join(", ")}. Those
            were left out of the score rather than guessed.
          </p>
        )}
      </DetailBlock>
      <p className="t-meta text-ink-faint">
        Written by {memo.model}
        {memo.input_tokens !== null && memo.output_tokens !== null && (
          <>
            {" · "}
            <span className="num-table">
              {(memo.input_tokens + memo.output_tokens).toLocaleString("en-US")}
            </span>{" "}
            tokens
          </>
        )}
      </p>
    </div>
  );
}

function EarlierMemo({ memo }: { memo: Memo }) {
  return (
    <li className="flex flex-col gap-sp-2 border-t border-line py-sp-4 first:border-0 first:pt-0 sm:flex-row sm:items-center sm:gap-sp-4">
      <span className="num-table w-32 shrink-0 t-meta text-ink-faint">
        {memo.dated_at ? fmtDate(memo.dated_at) : `Run ${memo.run_id}`}
      </span>
      {memo.conviction !== null && (
        <ConvictionBar score={memo.conviction} className="w-36 shrink-0" />
      )}
      <span className="t-body text-ink-dim">{memo.variant_view}</span>
    </li>
  );
}

function TickerBlock({ ticker, index }: { ticker: InsightTicker; index: number }) {
  const meta = TREND_META[ticker.trend];
  const [latest, ...earlier] = ticker.memos;
  const name = companyName(ticker.ticker);

  return (
    <div className="animate-rise" style={{ "--stagger-index": index } as React.CSSProperties}>
      <Card>
        <div className="flex flex-col lg:flex-row">
          <div className="min-w-0 flex-1">
            <CardHeader
              trailing={
                <StatusPill tone={meta.tone}>
                  <meta.icon size={13} weight="bold" />
                  {meta.label}
                </StatusPill>
              }
            >
              <div className="min-w-0">
                <p className="t-display text-ink">{ticker.ticker}</p>
                {name && <p className="mt-[2px] t-body text-ink-faint">{name}</p>}
              </div>
            </CardHeader>

            <CardBody className="pt-sp-4 pb-sp-5">
              <p className="max-w-[74ch] t-lead text-ink">{latest.variant_view}</p>
              <div className="mt-sp-4 flex flex-wrap items-center gap-sp-3">
                <Tag>
                  {ticker.memos.length} note{ticker.memos.length === 1 ? "" : "s"}
                </Tag>
                {latest.dated_at && <Tag>Latest {fmtDate(latest.dated_at)}</Tag>}
                {ticker.conviction_delta !== null && (
                  <Tag>
                    <span className="num-table">{fmtPct(ticker.conviction_delta)}</span> since last
                    run
                  </Tag>
                )}
              </div>
            </CardBody>
          </div>

          <div className="shrink-0 border-t border-line px-sp-6 py-sp-5 lg:w-[290px] lg:border-t-0 lg:border-l">
            {ticker.conviction_now !== null && <ConvictionScore score={ticker.conviction_now} />}
          </div>
        </div>

        <CardFooter inset>
          <Disclosure label="Read the full write-up" openLabel="Hide the write-up">
            <div className="flex flex-col gap-sp-6">
              <LatestMemo memo={latest} />
              {earlier.length > 0 && (
                <DetailBlock label={`${earlier.length} earlier note${earlier.length === 1 ? "" : "s"}`}>
                  <ul className="flex flex-col">
                    {earlier.map((m) => (
                      <EarlierMemo key={m.run_id} memo={m} />
                    ))}
                  </ul>
                </DetailBlock>
              )}
            </div>
          </Disclosure>
        </CardFooter>
      </Card>
    </div>
  );
}

/**
 * Renamed from Research. What the screen actually holds is the accumulated
 * view on each name and how it has moved run over run — the arc a thesis
 * traces, not the raw output of the research step.
 */
export function InsightsScreen() {
  const { state, reload } = useAsyncData(fetchInsights, "Unexpected error loading insights.");

  const data = state.kind === "loaded" ? state.data : null;

  return (
    <ScreenShell
      title="Insights"
      subtitle="The current view on each name in plain English, and whether the case is getting stronger or weaker."
      actions={
        <Button onClick={reload} disabled={state.kind === "loading"}>
          <ArrowClockwise size={14} className={state.kind === "loading" ? "animate-spin" : ""} />
          Refresh
        </Button>
      }
    >
      {state.kind === "loading" && <LoadingSkeleton />}
      {state.kind === "error" && <ErrorPanel message={state.message} onRetry={reload} />}

      {data && (
        <Section
          title="Covered names"
          count={data.tickers.length}
          icon={<Lightbulb size={19} weight="fill" className="text-accent" />}
          subtitle={
            <>
              Ranked by <Term text="conviction" definition={GLOSSARY.conviction} />. Every earlier
              write-up is kept, so a case that quietly weakened leaves a trail.
            </>
          }
        >
          {data.tickers.length === 0 ? (
            <EmptyRow
              label="No research on file."
              hint="Write-ups appear here once a nightly run researches a name."
            />
          ) : (
            <div className="flex flex-col gap-sp-5">
              {data.tickers.map((t, i) => (
                <TickerBlock key={t.ticker} ticker={t} index={i} />
              ))}
            </div>
          )}
        </Section>
      )}
    </ScreenShell>
  );
}
