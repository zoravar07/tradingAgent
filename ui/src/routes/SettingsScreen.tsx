import { useState } from "react";
import { ArrowsCounterClockwise, Eye, FloppyDisk } from "@phosphor-icons/react";
import { fetchConfig, fieldKeyFromLoc, resetConfigToDefaults, updateConfig } from "../api/config";
import { useAsyncData } from "../lib/useAsyncData";
import type { ConfigResponse, EditableConfig } from "../types/settings";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ScreenShell, Section } from "../components/ui/ScreenShell";
import { StatusPill } from "../components/ui/StatusPill";
import { CheckboxField, NumberField, TextField } from "../components/settings/Field";

type SaveState = "idle" | "saving" | "saved" | "error";

/** A titled panel of fields. Same card grammar as every other screen. */
function SettingsGroup({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <Section title={title} subtitle={subtitle}>
      <Card>
        <div className="px-sp-6 py-sp-5">{children}</div>
      </Card>
    </Section>
  );
}

export function SettingsScreen() {
  // Settings both reads and writes config, so it keeps its own copy of the
  // form separate from the fetched value: the two diverge the moment you
  // type, and reload() must be able to throw the edits away.
  const { state, reload, setData } = useAsyncData(fetchConfig, "Unexpected error loading settings.");
  const [form, setForm] = useState<EditableConfig | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [rawOpen, setRawOpen] = useState(false);
  const [rawText, setRawText] = useState<string | null>(null);
  const [rawLoading, setRawLoading] = useState(false);

  const config = state.kind === "loaded" ? state.data : null;
  // Seed the form the first time config lands, and after a reload that
  // cleared it. Derived during render rather than in an effect — an effect
  // here would paint one frame of empty inputs first.
  const [seededFor, setSeededFor] = useState<ConfigResponse | null>(null);
  if (config && seededFor !== config) {
    setSeededFor(config);
    setForm(config.editable);
  }

  async function handleSave() {
    if (!form) return;
    setSaveState("saving");
    setSaveMessage(null);
    const result = await updateConfig(form);
    if (result.ok) {
      setData(() => result.data);
      setSeededFor(result.data);
      setForm(result.data.editable);
      setFieldErrors({});
      setSaveState("saved");
      setSaveMessage("Saved.");
      setTimeout(() => setSaveState("idle"), 2500);
    } else {
      const errors: Record<string, string> = {};
      for (const e of result.errors) errors[fieldKeyFromLoc(e.loc)] = e.msg;
      setFieldErrors(errors);
      setSaveState("error");
      setSaveMessage(
        `${result.errors.length} field${result.errors.length === 1 ? "" : "s"} failed validation.`,
      );
    }
  }

  async function handleReset() {
    if (
      !window.confirm("Reset every editable setting to its default value? This overwrites config.yaml.")
    )
      return;
    setSaveState("saving");
    const result = await resetConfigToDefaults();
    if (result.ok) {
      setData(() => result.data);
      setSeededFor(result.data);
      setForm(result.data.editable);
      setFieldErrors({});
      setSaveState("saved");
      setSaveMessage("Reset to defaults.");
      setTimeout(() => setSaveState("idle"), 2500);
    } else {
      setSaveState("error");
      setSaveMessage(
        "Reset failed validation — this shouldn't happen; the defaults themselves are invalid.",
      );
    }
  }

  async function handleViewCurrent() {
    if (rawOpen) {
      setRawOpen(false);
      return;
    }
    setRawOpen(true);
    setRawLoading(true);
    try {
      const data = await fetchConfig();
      setRawText(data.yaml_text);
    } catch {
      setRawText(null);
    } finally {
      setRawLoading(false);
    }
  }

  return (
    <ScreenShell
      title="Settings"
      subtitle="The rules the nightly run follows. Every change here is written to config.yaml."
      actions={
        <div className="flex flex-wrap items-center justify-end gap-sp-2">
          {saveMessage && (
            <StatusPill tone={saveState === "error" ? "loss" : "gain"}>{saveMessage}</StatusPill>
          )}
          <Button onClick={handleViewCurrent}>
            <Eye size={14} />
            {rawOpen ? "Hide raw" : "View current"}
          </Button>
          <Button onClick={handleReset} disabled={saveState === "saving"}>
            <ArrowsCounterClockwise size={14} />
            Reset to defaults
          </Button>
          <Button variant="primary" onClick={handleSave} disabled={saveState === "saving" || !form}>
            <FloppyDisk size={14} />
            {saveState === "saving" ? "Saving…" : "Save"}
          </Button>
        </div>
      }
    >
      {state.kind === "loading" && <LoadingSkeleton />}
      {state.kind === "error" && <ErrorPanel message={state.message} onRetry={reload} />}

      {state.kind === "loaded" && form && config && (
        <>
          {rawOpen && (
            <SettingsGroup title="Raw config.yaml">
              {rawLoading ? (
                <p className="t-body text-ink-faint">Loading…</p>
              ) : rawText ? (
                <pre className="num-table max-h-96 overflow-auto rounded-inner bg-inset p-sp-4 t-meta whitespace-pre-wrap text-ink-dim">
                  {rawText}
                </pre>
              ) : (
                <p className="t-body text-loss">Couldn't load the raw file.</p>
              )}
            </SettingsGroup>
          )}

          <SettingsGroup title="Portfolio">
            <div className="grid grid-cols-1 gap-x-sp-6 gap-y-sp-5 sm:grid-cols-2">
              <div className="flex items-end pb-sp-2">
                <CheckboxField
                  label="Allow fractional shares (manual entry)"
                  checked={form.portfolio.allow_fractional}
                  onChange={(v) =>
                    setForm({ ...form, portfolio: { ...form.portfolio, allow_fractional: v } })
                  }
                />
              </div>
            </div>
          </SettingsGroup>

          <SettingsGroup title="Risk">
            <div className="grid grid-cols-1 gap-x-sp-6 gap-y-sp-5 sm:grid-cols-2 lg:grid-cols-3">
              <NumberField label="Max position (% NAV)" value={form.risk.max_position_pct}
                onChange={(v) => setForm({ ...form, risk: { ...form.risk, max_position_pct: v } })}
                error={fieldErrors["risk.max_position_pct"]} />
              <NumberField label="Max sector (% NAV)" value={form.risk.max_sector_pct}
                onChange={(v) => setForm({ ...form, risk: { ...form.risk, max_sector_pct: v } })}
                error={fieldErrors["risk.max_sector_pct"]} />
              <NumberField label="Max correlated cluster (% NAV)" value={form.risk.max_correlated_cluster_pct}
                onChange={(v) => setForm({ ...form, risk: { ...form.risk, max_correlated_cluster_pct: v } })}
                error={fieldErrors["risk.max_correlated_cluster_pct"]} />
              <NumberField label="Max daily proposals" value={form.risk.max_daily_proposals}
                onChange={(v) => setForm({ ...form, risk: { ...form.risk, max_daily_proposals: v } })}
                error={fieldErrors["risk.max_daily_proposals"]} />
              <NumberField label="Max daily loss (%)" value={form.risk.max_daily_loss_pct}
                onChange={(v) => setForm({ ...form, risk: { ...form.risk, max_daily_loss_pct: v } })}
                error={fieldErrors["risk.max_daily_loss_pct"]} />
              <NumberField label="Max drawdown (%)" value={form.risk.max_drawdown_pct}
                onChange={(v) => setForm({ ...form, risk: { ...form.risk, max_drawdown_pct: v } })}
                error={fieldErrors["risk.max_drawdown_pct"]} />
              <NumberField label="Min order value (USD)" value={form.risk.min_order_value_usd}
                onChange={(v) => setForm({ ...form, risk: { ...form.risk, min_order_value_usd: v } })}
                error={fieldErrors["risk.min_order_value_usd"]} />
              <NumberField label="Min hold conviction (floor)" value={form.risk.min_hold_conviction}
                onChange={(v) => setForm({ ...form, risk: { ...form.risk, min_hold_conviction: v } })}
                error={fieldErrors["risk.min_hold_conviction"]} />
              <NumberField label="Max unpriced held positions" value={form.risk.max_unpriced_held_positions}
                onChange={(v) => setForm({ ...form, risk: { ...form.risk, max_unpriced_held_positions: v } })}
                error={fieldErrors["risk.max_unpriced_held_positions"]} />
            </div>
          </SettingsGroup>

          <SettingsGroup title="Screener — Stage 1">
            <div className="grid grid-cols-1 gap-x-sp-6 gap-y-sp-5 sm:grid-cols-2 lg:grid-cols-3">
              <NumberField label="Min avg daily volume (USD)" value={form.screener.stage1.min_avg_daily_volume_usd}
                onChange={(v) => setForm({ ...form, screener: { stage1: { ...form.screener.stage1, min_avg_daily_volume_usd: v } } })}
                error={fieldErrors["screener.stage1.min_avg_daily_volume_usd"]} />
              <NumberField label="Min market cap (USD)" value={form.screener.stage1.min_market_cap_usd}
                onChange={(v) => setForm({ ...form, screener: { stage1: { ...form.screener.stage1, min_market_cap_usd: v } } })}
                error={fieldErrors["screener.stage1.min_market_cap_usd"]} />
              <NumberField label="Max survivors" value={form.screener.stage1.max_survivors}
                onChange={(v) => setForm({ ...form, screener: { stage1: { ...form.screener.stage1, max_survivors: v } } })}
                error={fieldErrors["screener.stage1.max_survivors"]} />
              <NumberField label="Min revenue growth (%)" value={form.screener.stage1.min_revenue_growth_pct}
                onChange={(v) => setForm({ ...form, screener: { stage1: { ...form.screener.stage1, min_revenue_growth_pct: v } } })}
                error={fieldErrors["screener.stage1.min_revenue_growth_pct"]} />
              <NumberField label="Valuation: cheap P/E max" value={form.screener.stage1.valuation_pe_cheap_max}
                onChange={(v) => setForm({ ...form, screener: { stage1: { ...form.screener.stage1, valuation_pe_cheap_max: v } } })}
                error={fieldErrors["screener.stage1.valuation_pe_cheap_max"]} />
              <NumberField label="Valuation: expensive P/E min" value={form.screener.stage1.valuation_pe_expensive_min}
                onChange={(v) => setForm({ ...form, screener: { stage1: { ...form.screener.stage1, valuation_pe_expensive_min: v } } })}
                error={fieldErrors["screener.stage1.valuation_pe_expensive_min"]} />
              <NumberField label="Earnings proximity (days)" value={form.screener.stage1.earnings_proximity_days}
                onChange={(v) => setForm({ ...form, screener: { stage1: { ...form.screener.stage1, earnings_proximity_days: v } } })}
                error={fieldErrors["screener.stage1.earnings_proximity_days"]} />
            </div>
          </SettingsGroup>

          <div className="grid grid-cols-1 gap-sp-6 md:grid-cols-2">
            <SettingsGroup title="Budget">
              <NumberField label="Monthly API cap (USD)" value={form.budget.monthly_api_cap_usd}
                onChange={(v) => setForm({ ...form, budget: { monthly_api_cap_usd: v } })}
                error={fieldErrors["budget.monthly_api_cap_usd"]} />
            </SettingsGroup>

            <SettingsGroup title="Schedule">
              <TextField label="Nightly run (cron)" value={form.schedule.nightly_run}
                placeholder="0 22 * * 0-4"
                onChange={(v) => setForm({ ...form, schedule: { nightly_run: v } })}
                error={fieldErrors["schedule.nightly_run"]} />
            </SettingsGroup>
          </div>

          <p className="t-meta text-ink-faint">
            Universe (watchlist, cluster overrides), conviction weights, and a few unmodeled sections
            (sleeves, sources, options) aren't editable here — use "View current" for the full file.
          </p>
        </>
      )}
    </ScreenShell>
  );
}
