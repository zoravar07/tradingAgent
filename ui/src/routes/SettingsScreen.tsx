import { useCallback, useEffect, useState } from "react";
import { ArrowsCounterClockwise, Eye, FloppyDisk } from "@phosphor-icons/react";
import { ApiError } from "../api/client";
import { fetchConfig, fieldKeyFromLoc, resetConfigToDefaults, updateConfig } from "../api/config";
import type { ConfigResponse, EditableConfig } from "../types/settings";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { StatusPill } from "../components/StatusPill";
import { SectionShell } from "../components/briefing/SectionShell";
import { CheckboxField, NumberField, TextField } from "../components/settings/Field";

type LoadState = { kind: "loading" } | { kind: "error"; message: string } | { kind: "loaded" };

type SaveState = "idle" | "saving" | "saved" | "error";

export function SettingsScreen() {
  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" });
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [form, setForm] = useState<EditableConfig | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [rawOpen, setRawOpen] = useState(false);
  const [rawText, setRawText] = useState<string | null>(null);
  const [rawLoading, setRawLoading] = useState(false);

  const load = useCallback(async () => {
    setLoadState({ kind: "loading" });
    try {
      const data = await fetchConfig();
      setConfig(data);
      setForm(data.editable);
      setLoadState({ kind: "loaded" });
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Unexpected error loading settings.";
      setLoadState({ kind: "error", message });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave() {
    if (!form) return;
    setSaveState("saving");
    setSaveMessage(null);
    const result = await updateConfig(form);
    if (result.ok) {
      setConfig(result.data);
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
      setSaveMessage(`${result.errors.length} field${result.errors.length === 1 ? "" : "s"} failed validation.`);
    }
  }

  async function handleReset() {
    if (!window.confirm("Reset every editable setting to its default value? This overwrites config.yaml.")) return;
    setSaveState("saving");
    const result = await resetConfigToDefaults();
    if (result.ok) {
      setConfig(result.data);
      setForm(result.data.editable);
      setFieldErrors({});
      setSaveState("saved");
      setSaveMessage("Reset to defaults.");
      setTimeout(() => setSaveState("idle"), 2500);
    } else {
      setSaveState("error");
      setSaveMessage("Reset failed validation — this shouldn't happen; the defaults themselves are invalid.");
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
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-[var(--color-hairline)] px-8 py-5">
        <div>
          <h1 className="text-lg font-semibold text-[var(--color-ink)]">Settings</h1>
          {saveMessage && (
            <div className="mt-1 flex items-center gap-2">
              <StatusPill tone={saveState === "error" ? "loss" : "gain"}>{saveMessage}</StatusPill>
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={handleViewCurrent}
            className="flex items-center gap-1.5 rounded-md border border-[var(--color-hairline-strong)] px-3 py-1.5 text-xs font-medium text-[var(--color-ink-dim)] transition-colors hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)] active:scale-[0.98]"
          >
            <Eye size={13} />
            {rawOpen ? "Hide raw" : "View current"}
          </button>
          <button
            onClick={handleReset}
            disabled={saveState === "saving"}
            className="flex items-center gap-1.5 rounded-md border border-[var(--color-hairline-strong)] px-3 py-1.5 text-xs font-medium text-[var(--color-ink-dim)] transition-colors hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)] active:scale-[0.98] disabled:opacity-50"
          >
            <ArrowsCounterClockwise size={13} />
            Reset to defaults
          </button>
          <button
            onClick={handleSave}
            disabled={saveState === "saving" || !form}
            className="flex items-center gap-1.5 rounded-md bg-[var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-[#06101f] transition-colors hover:opacity-90 active:scale-[0.98] disabled:opacity-50"
          >
            <FloppyDisk size={13} />
            {saveState === "saving" ? "Saving…" : "Save"}
          </button>
        </div>
      </header>

      {loadState.kind === "loading" && <LoadingSkeleton />}
      {loadState.kind === "error" && <ErrorPanel message={loadState.message} onRetry={load} />}
      {loadState.kind === "loaded" && form && config && (
        <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-8 py-6">
          {rawOpen && (
            <SectionShell title="Raw config.yaml">
              {rawLoading ? (
                <p className="text-sm text-[var(--color-ink-faint)]">Loading…</p>
              ) : rawText ? (
                <pre className="num max-h-96 overflow-auto whitespace-pre-wrap text-xs text-[var(--color-ink-dim)]">
                  {rawText}
                </pre>
              ) : (
                <p className="text-sm text-[var(--color-loss)]">Couldn't load the raw file.</p>
              )}
            </SectionShell>
          )}

          <SectionShell title="Portfolio">
            <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
              <NumberField
                label="Import reminder (days)"
                value={form.portfolio.import_reminder_days}
                onChange={(v) => setForm({ ...form, portfolio: { ...form.portfolio, import_reminder_days: v } })}
                error={fieldErrors["portfolio.import_reminder_days"]}
              />
              <div className="flex items-end pb-1.5">
                <CheckboxField
                  label="Allow fractional shares (manual entry)"
                  checked={form.portfolio.allow_fractional}
                  onChange={(v) => setForm({ ...form, portfolio: { ...form.portfolio, allow_fractional: v } })}
                />
              </div>
            </div>
          </SectionShell>

          <SectionShell title="Risk">
            <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
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
          </SectionShell>

          <SectionShell title="Screener — Stage 1">
            <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
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
          </SectionShell>

          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <SectionShell title="Budget">
              <NumberField label="Monthly API cap (USD)" value={form.budget.monthly_api_cap_usd}
                onChange={(v) => setForm({ ...form, budget: { monthly_api_cap_usd: v } })}
                error={fieldErrors["budget.monthly_api_cap_usd"]} />
            </SectionShell>

            <SectionShell title="Schedule">
              <TextField label="Nightly run (cron)" value={form.schedule.nightly_run}
                placeholder="0 22 * * 0-4"
                onChange={(v) => setForm({ ...form, schedule: { nightly_run: v } })}
                error={fieldErrors["schedule.nightly_run"]} />
            </SectionShell>
          </div>

          <p className="pb-2 text-xs text-[var(--color-ink-faint)]">
            Universe (watchlist, cluster overrides), conviction weights, and a few unmodeled sections
            (sleeves, sources, options) aren't editable here — see "View current" for the full file.
          </p>
        </div>
      )}
    </div>
  );
}
