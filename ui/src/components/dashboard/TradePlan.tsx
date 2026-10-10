import type { Setup, TradePlan as Plan } from "../../types/dashboard";
import { fmtPctPlain, fmtUsd2, shareParts } from "../../lib/format";
import { companyName } from "../../lib/tickers";
import { ConvictionBar } from "../ui/ConvictionBar";
import { StatusPill } from "../ui/StatusPill";

function Row({ label, value, tone, hint }: { label: string; value: string | null; tone?: "gain" | "loss"; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-sp-3 py-sp-2">
      <dt className="t-meta text-ink-faint">{label}</dt>
      <dd className="text-right">
        <span
          className={`num-table t-body font-semibold ${
            value === null ? "text-ink-faint" : tone === "gain" ? "text-gain" : tone === "loss" ? "text-loss" : "text-ink"
          }`}
        >
          {value ?? "—"}
        </span>
        {hint && <p className="t-meta text-ink-faint">{hint}</p>}
      </dd>
    </div>
  );
}

/**
 * The plan for the selected name, from the pipeline's own trigger math:
 * entry is the limit price (or cost basis for a holding), stop is the
 * trailing stop the risk rules would fire at, target is the profit-taking
 * band. Anything the data can't support shows a dash — no risk:reward, no
 * time horizon, because nothing computes those.
 */
export function TradePlan({ setup, plan }: { setup: Setup | null; plan: Plan | null }) {
  if (!setup || !plan) {
    return <p className="px-sp-5 py-sp-6 t-body text-ink-faint">Select a name to see its plan.</p>;
  }
  const qty = plan.quantity === null ? null : shareParts(plan.quantity);
  return (
    <div className="flex flex-col gap-sp-4 px-sp-5 py-sp-4">
      <div className="flex items-start justify-between gap-sp-3">
        <div className="min-w-0">
          <p className="t-title text-ink">{setup.ticker}</p>
          {(setup.name ?? companyName(setup.ticker)) && <p className="t-meta text-ink-faint">{setup.name ?? companyName(setup.ticker)}</p>}
        </div>
        <StatusPill tone={setup.action === "BUY" ? "buy" : setup.action === "CANDIDATE" ? "accent" : "sell"}>
          {setup.action === "TRIM" ? "Sell / Trim" : setup.action === "CANDIDATE" ? "Candidate" : setup.action}
        </StatusPill>
      </div>

      <div className="grid grid-cols-1 gap-x-sp-6 sm:grid-cols-2">
        <dl className="divide-y divide-line">
          <Row
            label="Entry price"
            value={plan.entry_price === null ? null : fmtUsd2(plan.entry_price)}
            hint={plan.entry_basis ?? undefined}
          />
          <Row
            label="Stop loss"
            value={plan.stop_price === null ? null : fmtUsd2(plan.stop_price)}
            tone="loss"
            hint={plan.stop_price === null ? "needs a peak price and ATR" : `peak − ATR multiple (ATR ${plan.atr_14?.toFixed(2)})`}
          />
          <Row
            label="Take profit"
            value={plan.target_price === null ? null : fmtUsd2(plan.target_price)}
            tone="gain"
            hint={plan.target_pct === null ? "held positions only" : `${fmtPctPlain(plan.target_pct)} above cost`}
          />
        </dl>
        <dl className="divide-y divide-line">
          <Row label="Position size" value={qty ? `${qty.figure} ${qty.unit}` : null} />
          <Row label="Est. cost" value={plan.est_cost_usd === null ? null : fmtUsd2(plan.est_cost_usd)} />
          <Row label="Weight" value={plan.weight_pct === null ? null : fmtPctPlain(plan.weight_pct)} hint="of portfolio" />
        </dl>
      </div>

      <div className="flex flex-col gap-sp-1">
        <div className="flex items-baseline justify-between">
          <span className="t-meta text-ink-faint">Confidence</span>
          <span className="num-table t-meta text-ink-dim">
            {plan.conviction === null ? "no score" : `${Math.round(plan.conviction)} / 100`}
          </span>
        </div>
        {plan.conviction !== null && <ConvictionBar score={plan.conviction} showValue={false} />}
      </div>
    </div>
  );
}
