import { ArrowClockwise, ChartLineUp, Info } from "@phosphor-icons/react";
import { fetchPerformance } from "../api/client";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { fmtDate, fmtDateTime, fmtPct, fmtPctPlain, fmtUsd } from "../lib/format";
import { GLOSSARY } from "../lib/glossary";
import { useAsyncData } from "../lib/useAsyncData";
import { Button } from "../components/ui/Button";
import { Callout } from "../components/ui/Callout";
import { Card } from "../components/ui/Card";
import { EmptyRow, ScreenShell, Section } from "../components/ui/ScreenShell";
import { LineChart } from "../components/ui/LineChart";
import { StatRow } from "../components/ui/StatRow";
import { Term } from "../components/ui/Term";

/**
 * Portfolio value over time, from nav_snapshots — one row written per run by
 * the pipeline itself.
 *
 * Honest about what it has. Two readings is the minimum that draws a line;
 * below that the screen says there isn't enough history yet instead of
 * rendering a chart of one dot. And with a handful of runs it says that too:
 * the caption names the number of readings, because a four-point line is a
 * record of four nights, not a performance track record, and drawing it at
 * full width invites reading it as the latter.
 */
export function PerformanceScreen() {
  const { state, reload } = useAsyncData(fetchPerformance, "Unexpected error loading performance.");

  const data = state.kind === "loaded" ? state.data : null;

  return (
    <ScreenShell
      title="Performance"
      subtitle={
        data?.source === "ibkr"
          ? "Your account's value over time, one reading per day from Interactive Brokers."
          : "Portfolio value over time, one estimate per nightly run."
      }
      actions={
        <Button onClick={reload} disabled={state.kind === "loading"}>
          <ArrowClockwise size={14} className={state.kind === "loading" ? "animate-spin" : ""} />
          Refresh
        </Button>
      }
    >
      {state.kind === "loading" && <LoadingSkeleton />}
      {state.kind === "error" && <ErrorPanel message={state.message} onRetry={reload} />}

      {data && data.point_count === 0 && (
        <EmptyRow
          label="Not enough history yet — check back after a few runs."
          hint="No run has recorded a portfolio value yet. One reading is written per nightly run."
        />
      )}

      {data && data.point_count === 1 && (
        <>
          <EmptyRow
            label="Not enough history yet — check back after a few runs."
            hint="One reading so far. A line needs at least two, so there's nothing to plot until the next run."
          />
          <Card>
            <div className="px-sp-6 py-sp-5">
              <StatRow
                columns={3}
                stats={[
                  {
                    label: "Portfolio Value",
                    value: data.current_nav_usd === null ? "—" : fmtUsd(data.current_nav_usd),
                    hint: data.series[0] ? fmtDate(data.series[0].recorded_at) : undefined,
                  },
                  { label: "Readings", value: "1", unit: data.source === "ibkr" ? "day" : "run" },
                  {
                    label: "Drawdown",
                    value: data.drawdown_pct === null ? "—" : fmtPctPlain(data.drawdown_pct),
                    hint: "from peak",
                  },
                ]}
              />
            </div>
          </Card>
        </>
      )}

      {data && data.has_history && (
        <>
          <Card>
            <div className="px-sp-6 py-sp-5">
              <StatRow
                stats={[
                  {
                    label: "Portfolio Value",
                    value: data.current_nav_usd === null ? "—" : fmtUsd(data.current_nav_usd),
                    hint: "latest run",
                  },
                  {
                    label: "Peak",
                    value: data.peak_nav_usd === null ? "—" : fmtUsd(data.peak_nav_usd),
                    hint: "highest reading",
                  },
                  {
                    label: "Drawdown",
                    value: data.drawdown_pct === null ? "—" : fmtPctPlain(data.drawdown_pct),
                    hint: "from peak",
                    tone: (data.drawdown_pct ?? 0) > 0 ? "loss" : undefined,
                  },
                  {
                    label: "Readings",
                    value: String(data.point_count),
                    unit: data.source === "ibkr" ? (data.point_count === 1 ? "day" : "days") : data.point_count === 1 ? "run" : "runs",
                  },
                ]}
              />
            </div>
          </Card>

          <Section
            title="Portfolio value"
            icon={<ChartLineUp size={19} weight="fill" className="text-accent" />}
          >
            <Card>
              <div className="px-sp-6 py-sp-5">
                <LineChart
                  points={data.series.map((s) => ({
                    x: s.recorded_at,
                    y: s.nav_usd,
                    label: s.run_id === null ? fmtDate(s.recorded_at) : `Run ${s.run_id}`,
                  }))}
                  caption={`${data.point_count} readings, ${fmtDate(
                    data.series[0].recorded_at,
                  )} to ${fmtDate(data.series[data.series.length - 1].recorded_at)}. The vertical axis is scaled to the range of the data, not to zero.`}
                />
              </div>
            </Card>
          </Section>

          <Callout icon={Info} title="Read this as a log, not a track record.">
            {data.point_count} readings over{" "}
            {Math.max(
              1,
              Math.round(
                (new Date(data.series[data.series.length - 1].recorded_at).getTime() -
                  new Date(data.series[0].recorded_at).getTime()) /
                  86_400_000,
              ),
            )}{" "}
            day(s) is a record of what the book was worth on those nights. Early readings predate the
            full book being priced, so the change between the first and last point isn't a return.
          </Callout>

          <Section
            title="Readings"
            count={data.point_count}
            subtitle={
              <>
                {data.source === "ibkr" ? "Every daily value synced from the broker" : "Every value the pipeline has estimated"}, with the{" "}
                <Term text="drawdown" definition={GLOSSARY.drawdown} /> it computed at the time.
              </>
            }
          >
            <Card>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[42rem] border-collapse">
                  <thead>
                    <tr className="border-b border-line bg-inset">
                      <th className="px-sp-5 py-sp-3 text-left t-meta font-medium text-ink-faint">
                        Run
                      </th>
                      <th className="px-sp-5 py-sp-3 text-left t-meta font-medium text-ink-faint">
                        Recorded
                      </th>
                      <th className="px-sp-5 py-sp-3 text-right t-meta font-medium text-ink-faint">
                        Portfolio value
                      </th>
                      <th className="px-sp-5 py-sp-3 text-right t-meta font-medium text-ink-faint">
                        Peak
                      </th>
                      <th className="px-sp-5 py-sp-3 text-right t-meta font-medium text-ink-faint">
                        Drawdown
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...data.series].reverse().map((s) => (
                      <tr key={s.recorded_at} className="border-b border-line last:border-0">
                        <td className="px-sp-5 py-sp-3 t-body text-ink">{s.run_id === null ? "Broker" : `Run ${s.run_id}`}</td>
                        <td className="px-sp-5 py-sp-3 t-body text-ink-dim">
                          {fmtDateTime(s.recorded_at)}
                        </td>
                        <td className="num-table px-sp-5 py-sp-3 text-right t-body font-medium text-ink">
                          {fmtUsd(s.nav_usd)}
                        </td>
                        <td className="num-table px-sp-5 py-sp-3 text-right t-body text-ink-dim">
                          {fmtUsd(s.peak_nav_usd)}
                        </td>
                        <td
                          className={`num-table px-sp-5 py-sp-3 text-right t-body ${
                            s.drawdown_pct > 0 ? "text-loss" : "text-ink-dim"
                          }`}
                        >
                          {fmtPctPlain(s.drawdown_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </Section>

          {data.change_since_first_pct !== null && (
            <p className="t-meta text-ink-faint">
              Change from the first reading to the latest:{" "}
              <span className="num-table font-medium text-ink-dim">
                {fmtPct(data.change_since_first_pct)}
              </span>
              . Not a return — see the note above.
            </p>
          )}
        </>
      )}
    </ScreenShell>
  );
}
