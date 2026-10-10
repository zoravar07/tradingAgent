import { ArrowClockwise, ChartLine, Lightbulb, ListChecks, Prohibit, Target, WarningCircle } from "@phosphor-icons/react";
import { useState } from "react";
import { fetchDashboard, fetchLatestBriefing } from "../api/client";
import type { Briefing } from "../types/briefing";
import type { DashboardResponse, Setup } from "../types/dashboard";
import { EmptyState } from "../components/EmptyState";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { fmtPctPlain, greetingFor } from "../lib/format";
import { useAsyncData } from "../lib/useAsyncData";
import { Button, ButtonLink } from "../components/ui/Button";
import { Callout } from "../components/ui/Callout";
import { Card } from "../components/ui/Card";
import { ScreenShell } from "../components/ui/ScreenShell";
import { InsightsList } from "../components/dashboard/InsightsList";
import { PnlStrip } from "../components/dashboard/PnlStrip";
import { PriceChart } from "../components/dashboard/PriceChart";
import { TodoList } from "../components/dashboard/TodoList";
import { TradePlan } from "../components/dashboard/TradePlan";

/**
 * The daily page, kept deliberately plain: how the portfolio moved, how
 * many names are held, what the month has cost, and a short to-do list of
 * trades. Selecting a trade (or, when there are none, a holding) fills the
 * chart, plan and insight panels under it.
 */
export function BriefingScreen() {
  const briefingState = useAsyncData(fetchLatestBriefing, "Unexpected error loading the briefing.");
  const dashState = useAsyncData(fetchDashboard, "Unexpected error loading the dashboard.");
  const loading = briefingState.state.kind === "loading" || dashState.state.kind === "loading";
  const reload = () => {
    briefingState.reload();
    dashState.reload();
  };

  const briefing =
    briefingState.state.kind === "loaded" && briefingState.state.data.status === "ok" ? briefingState.state.data.briefing : null;
  const dash = dashState.state.kind === "loaded" && dashState.state.data.status === "ok" ? dashState.state.data : null;
  const noRuns =
    (briefingState.state.kind === "loaded" && briefingState.state.data.status === "no_runs_yet") ||
    (dashState.state.kind === "loaded" && dashState.state.data.status === "no_runs_yet");
  const error =
    briefingState.state.kind === "error" ? briefingState.state.message : dashState.state.kind === "error" ? dashState.state.message : null;

  return (
    <ScreenShell
      title={`${greetingFor(new Date())}, Zoravar.`}
      subtitle="Here's your daily briefing."
      actions={
        <Button onClick={reload} disabled={loading}>
          <ArrowClockwise size={14} className={loading ? "animate-spin" : ""} />
          Refresh
        </Button>
      }
    >
      {loading && <LoadingSkeleton />}
      {!loading && error && <ErrorPanel message={error} onRetry={reload} />}
      {!loading && !error && noRuns && <EmptyState />}
      {!loading && !error && briefing && dash && <Daily briefing={briefing} dash={dash} />}
    </ScreenShell>
  );
}

function Daily({ briefing, dash }: { briefing: Briefing; dash: Extract<DashboardResponse, { status: "ok" }> }) {
  const actions: Setup[] = dash.setups.filter((s) => s.action !== "CANDIDATE");
  // Selection is derived: the chosen name if it still exists, else the first
  // trade, else the largest holding. Holdings are selectable through the
  // Positions page; here the panels follow the to-do list.
  const [chosen, setChosen] = useState<string | null>(null);
  const selectable = [...actions.map((a) => a.ticker), ...dash.holdings.map((h) => h.ticker)];
  const selected = chosen && selectable.includes(chosen) ? chosen : (selectable[0] ?? null);
  const selectedSetup: Setup | null =
    actions.find((a) => a.ticker === selected) ??
    (() => {
      const h = dash.holdings.find((x) => x.ticker === selected);
      return h
        ? { ticker: h.ticker, name: h.name, action: "CANDIDATE" as const, conviction: h.conviction, price: h.price, change_pct: h.change_pct, is_held: true, weight_pct: h.weight_pct, order: null, reason: null }
        : null;
    })();
  const selectedName = selectedSetup?.name ?? null;

  const health = briefing.portfolio_health;
  const killTriggered = health.kill_switch?.triggered ?? false;
  const spend = dash.tiles.find((t) => t.key === "api_spend_mtd");

  if (briefing.blocked) {
    return (
      <Card tone="sell">
        <div className="flex items-start gap-sp-4 px-sp-6 py-sp-5">
          <Prohibit size={26} weight="duotone" className="shrink-0 text-loss" />
          <div>
            <p className="t-title text-ink">This run is blocked — nothing here is safe to act on</p>
            <p className="mt-sp-1 t-body text-ink-dim">{briefing.blocked.reason}</p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <>
      {killTriggered && (
        <Callout icon={Prohibit} tone="loss" title="The kill switch has tripped.">
          {health.kill_switch?.reasons.join(" · ") ?? "New trades are paused until you clear it in Settings."}
        </Callout>
      )}
      {briefing.unresearched_holdings.length > 0 && (
        <Callout
          icon={WarningCircle}
          tone="risk"
          title={`${briefing.unresearched_holdings.length} holding${briefing.unresearched_holdings.length === 1 ? "" : "s"} could not be researched this run.`}
          action={
            <ButtonLink to="/positions" variant="outline" size="md">
              See positions
            </ButtonLink>
          }
        >
          {briefing.unresearched_holdings.map((h) => h.ticker).join(", ")} — no fresh score, so no exit trigger was checked for them.
        </Callout>
      )}

      <div className="flex flex-col gap-sp-3 lg:flex-row">
        <PnlStrip pnl={dash.pnl} />
        <div className="flex shrink-0 divide-x divide-line rounded-card border border-line bg-surface shadow-card">
          <div className="flex flex-col gap-[2px] px-sp-4 py-sp-3">
            <span className="t-meta text-ink-faint">Positions</span>
            <span className="t-stat text-ink">{dash.holdings.length}</span>
            <span className="t-meta text-ink-faint">held · cash {fmtPctPlain(health.cash_pct)}</span>
          </div>
          <div className="flex flex-col gap-[2px] px-sp-4 py-sp-3">
            <span className="t-meta text-ink-faint">API cost</span>
            <span className="t-stat text-ink">{spend ? `$${spend.value.toFixed(2)}` : "—"}</span>
            <span className="t-meta text-ink-faint">{spend?.cap ? `this month, of $${spend.cap.toFixed(0)}` : "this month"}</span>
          </div>
        </div>
      </div>

      <Panel title="To do today" icon={<ListChecks size={17} weight="fill" className="text-accent" />} count={Math.min(actions.length, 5)}>
        <TodoList actions={actions} selected={selected} onSelect={setChosen} />
      </Panel>

      <div className="grid grid-cols-1 items-start gap-sp-4 lg:grid-cols-2">
        <Panel title="Price" icon={<ChartLine size={17} weight="fill" className="text-accent" />}>
          <PriceChart ticker={selected} name={selectedName} />
        </Panel>
        <Panel title="Trade plan" icon={<Target size={17} weight="fill" className="text-accent" />} link={{ to: "/positions", label: "Positions" }}>
          <TradePlan setup={selectedSetup} plan={selected ? (dash.plans[selected] ?? null) : null} />
        </Panel>
      </div>
      <Panel title="Insights" icon={<Lightbulb size={17} weight="fill" className="text-accent" />} link={{ to: "/insights", label: "All insights" }}>
        <InsightsList ticker={selected} insight={selected ? (dash.insights[selected] ?? null) : null} />
      </Panel>
    </>
  );
}

function Panel({ title, icon, count, link, children }: { title: string; icon?: React.ReactNode; count?: number; link?: { to: string; label: string }; children: React.ReactNode }) {
  return (
    <Card className="min-w-0 overflow-hidden">
      <div className="flex items-center justify-between gap-sp-3 border-b border-line px-sp-5 py-sp-3">
        <div className="flex items-center gap-sp-2">
          {icon}
          <h2 className="t-title text-ink">{title}</h2>
          {count !== undefined && (
            <span className="num-table rounded-chip bg-inset-strong px-sp-2 py-[2px] t-meta font-medium text-ink-dim">{count}</span>
          )}
        </div>
        {link && (
          <ButtonLink to={link.to} variant="ghost" size="sm">
            {link.label} →
          </ButtonLink>
        )}
      </div>
      <div className="min-w-0">{children}</div>
    </Card>
  );
}
