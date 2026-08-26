import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import type { PortfolioHealth } from "../../types/briefing";
import { SectionShell } from "./SectionShell";

function SleeveBar({ name, actual, target }: { name: string; actual: number; target?: number }) {
  const pct = Math.min(actual, 100);
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 shrink-0 truncate text-sm text-[var(--color-ink-dim)]">{name}</span>
      <div className="relative h-1.5 flex-1 rounded-full bg-[var(--color-hairline)]">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-[var(--color-accent)]"
          style={{ width: `${pct}%` }}
        />
        {target !== undefined && (
          <div
            className="absolute top-1/2 h-2.5 w-[2px] -translate-y-1/2 bg-[var(--color-ink)]"
            style={{ left: `${Math.min(target, 100)}%` }}
            title={`target ${target.toFixed(1)}%`}
          />
        )}
      </div>
      <span className="num w-14 shrink-0 text-right text-sm text-[var(--color-ink)]">{actual.toFixed(1)}%</span>
    </div>
  );
}

export function HealthSection({ health }: { health: PortfolioHealth }) {
  const sleeveNames = Array.from(
    new Set([...Object.keys(health.sleeve_weights_pct), ...Object.keys(health.sleeve_targets_pct)]),
  ).sort();
  const clusterEntries = Object.entries(health.correlated_cluster_pct).sort((a, b) => b[1] - a[1]);
  const killTriggered = health.kill_switch?.triggered ?? false;

  return (
    <SectionShell title="Portfolio health">
      <div className="grid grid-cols-1 gap-4 border-b border-[var(--color-hairline)] pb-4 sm:grid-cols-3">
        <Stat label="Cash" value={`${health.cash_pct.toFixed(1)}%`} />
        <Stat
          label="Drawdown from peak"
          value={`${health.drawdown_from_peak_pct.toFixed(1)}%`}
          tone={health.drawdown_from_peak_pct > 0 ? "loss" : undefined}
        />
        <div>
          <p className="text-xs text-[var(--color-ink-faint)]">Kill switch</p>
          <div className="mt-1 flex items-center gap-1.5">
            {killTriggered ? (
              <WarningCircle size={16} weight="fill" className="text-[var(--color-loss)]" />
            ) : (
              <CheckCircle size={16} weight="fill" className="text-[var(--color-gain)]" />
            )}
            <span className={`text-sm font-medium ${killTriggered ? "text-[var(--color-loss)]" : "text-[var(--color-gain)]"}`}>
              {killTriggered ? "Triggered" : "OK"}
            </span>
          </div>
          {killTriggered && health.kill_switch && (
            <p className="mt-1 text-xs text-[var(--color-ink-dim)]">{health.kill_switch.reasons.join("; ")}</p>
          )}
        </div>
      </div>

      {sleeveNames.length > 0 && (
        <div className="flex flex-col gap-2.5 border-b border-[var(--color-hairline)] py-4">
          <p className="text-xs text-[var(--color-ink-faint)]">Sleeve weights vs. targets</p>
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
        <div className="pt-4">
          <p className="text-xs text-[var(--color-ink-faint)]">Correlated clusters</p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
            {clusterEntries.map(([name, pct]) => (
              <span key={name} className="text-sm">
                <span className="text-[var(--color-ink-dim)]">{name}</span>{" "}
                <span className="num font-medium text-[var(--color-ink)]">{pct.toFixed(1)}%</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </SectionShell>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "loss" }) {
  return (
    <div>
      <p className="text-xs text-[var(--color-ink-faint)]">{label}</p>
      <p className={`num mt-1 text-lg font-semibold ${tone === "loss" ? "text-[var(--color-loss)]" : "text-[var(--color-ink)]"}`}>
        {value}
      </p>
    </div>
  );
}
