import { ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import type { PortfolioHealth } from "../../types/briefing";
import { HelpTip } from "../HelpTip";
import { EmptySection, SectionShell } from "./SectionShell";

function SleeveBar({ name, actual, target }: { name: string; actual: number; target?: number }) {
  const barWidth = Math.min(Math.max(actual, 0), 100);
  const diff = target !== undefined ? actual - target : 0;
  const barTone =
    target === undefined || Math.abs(diff) < 5
      ? "bg-[var(--color-accent)]"
      : Math.abs(diff) >= 10
        ? "bg-[var(--color-loss)]"
        : "bg-[var(--color-risk)]";

  return (
    <div className="flex items-center gap-3">
      <span className="w-28 shrink-0 truncate text-sm text-[var(--color-ink-dim)]">{name}</span>
      <div className="relative h-1.5 flex-1 rounded-full bg-[var(--color-hairline)]">
        <div className={`absolute inset-y-0 left-0 rounded-full ${barTone}`} style={{ width: `${barWidth}%` }} />
        {target !== undefined && (
          <div
            className="absolute top-1/2 h-2.5 w-[2px] -translate-y-1/2 bg-[var(--color-ink)]"
            style={{ left: `${Math.min(Math.max(target, 0), 100)}%` }}
          />
        )}
      </div>
      <span className="num w-14 shrink-0 text-right text-sm text-[var(--color-ink)]">{actual.toFixed(1)}%</span>
      <span className="num w-20 shrink-0 text-right text-xs text-[var(--color-ink-faint)]">
        {target !== undefined ? `target ${target.toFixed(0)}%` : ""}
      </span>
    </div>
  );
}

function ClusterBar({ name, pct }: { name: string; pct: number }) {
  const tone = pct >= 40 ? "bg-[var(--color-risk)]" : "bg-[var(--color-accent)]";
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 shrink-0 truncate text-sm text-[var(--color-ink-dim)]">{name}</span>
      <div className="relative h-1.5 flex-1 rounded-full bg-[var(--color-hairline)]">
        <div className={`absolute inset-y-0 left-0 rounded-full ${tone}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="num w-14 shrink-0 text-right text-sm text-[var(--color-ink)]">{pct.toFixed(1)}%</span>
    </div>
  );
}

export function HealthSection({ health }: { health: PortfolioHealth }) {
  const sleeveNames = Array.from(
    new Set([...Object.keys(health.sleeve_weights_pct), ...Object.keys(health.sleeve_targets_pct)]),
  ).sort();
  const clusterEntries = Object.entries(health.correlated_cluster_pct).sort((a, b) => b[1] - a[1]);
  const killTriggered = health.kill_switch?.triggered ?? false;
  const hasContent = sleeveNames.length > 0 || clusterEntries.length > 0 || killTriggered;

  return (
    <SectionShell title="Portfolio health" subtitle="How balanced and risky your holdings are right now." icon={ShieldCheck}>
      {!hasContent && <EmptySection label="Nothing to review." />}

      {sleeveNames.length > 0 && (
        <div className="flex flex-col gap-2.5 border-b border-[var(--color-hairline)] pb-4">
          <p className="flex items-center gap-1 text-xs text-[var(--color-ink-faint)]">
            Sleeve weights vs. targets
            <HelpTip text="A 'sleeve' is a category of the portfolio (e.g. core or speculative) with its own target size." />
          </p>
          {sleeveNames.map((name) => (
            <SleeveBar
              key={name}
              name={name}
              actual={health.sleeve_weights_pct[name] ?? 0}
              target={health.sleeve_targets_pct[name]}
            />
          ))}
        </div>
      )}

      {clusterEntries.length > 0 && (
        <div className={`flex flex-col gap-2.5 ${sleeveNames.length > 0 ? "pt-4" : ""} ${killTriggered ? "border-b border-[var(--color-hairline)] pb-4" : ""}`}>
          <p className="text-xs text-[var(--color-ink-faint)]">Correlated clusters</p>
          {clusterEntries.map(([name, pct]) => (
            <ClusterBar key={name} name={name} pct={pct} />
          ))}
        </div>
      )}

      {killTriggered && health.kill_switch && (
        <div className={`flex items-start gap-2 rounded-lg border border-[var(--color-loss)]/30 bg-[var(--color-loss-wash)] p-3 ${sleeveNames.length > 0 || clusterEntries.length > 0 ? "mt-4" : ""}`}>
          <WarningCircle size={16} weight="fill" className="mt-0.5 shrink-0 text-[var(--color-loss)]" />
          <p className="text-xs text-[var(--color-ink-dim)]">{health.kill_switch.reasons.join("; ")}</p>
        </div>
      )}
    </SectionShell>
  );
}
