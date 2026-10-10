import { useState } from "react";
import { Notebook, Trash } from "@phosphor-icons/react";
import {
  ApiError,
  createJournalEntry,
  deleteJournalEntry,
  fetchJournal,
  fetchPositions,
} from "../api/client";
import { useAsyncData } from "../lib/useAsyncData";
import type { JournalEntry } from "../types/screens";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { fmtDate } from "../lib/format";
import { companyName } from "../lib/tickers";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyRow, ScreenShell, Section } from "../components/ui/ScreenShell";
import { Tag } from "../components/ui/StatusPill";
import { TickerMark } from "../components/ui/TickerMark";

/**
 * Held tickers populate the composer's suggestions — a note is almost
 * always about something you own. Declared at module scope so the hook's
 * fetcher identity is stable across renders.
 */
async function loadJournalScreen(): Promise<{ entries: JournalEntry[]; tickers: string[] }> {
  const [journal, positions] = await Promise.all([fetchJournal(), fetchPositions()]);
  return { entries: journal.entries, tickers: positions.positions.map((p) => p.ticker) };
}

/** Today as `yyyy-mm-dd` in local time — `toISOString` would use UTC and put
 * a late-evening note on tomorrow's date. */
function todayLocal(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function Composer({
  tickers,
  onSaved,
}: {
  tickers: string[];
  onSaved: (entry: JournalEntry) => void;
}) {
  const [content, setContent] = useState("");
  const [date, setDate] = useState(todayLocal());
  const [ticker, setTicker] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (!content.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const entry = await createJournalEntry({
        content,
        date,
        linked_ticker: ticker || null,
      });
      onSaved(entry);
      setContent("");
      setTicker("");
      setDate(todayLocal());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save that note.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-col gap-sp-4 px-sp-6 py-sp-5">
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={4}
          placeholder="What did you decide today, and why?"
          className="w-full resize-y rounded-inner border border-line bg-surface px-sp-4 py-sp-3 t-body text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
        />

        <div className="flex flex-wrap items-end gap-sp-4">
          <label className="flex flex-col gap-sp-2">
            <span className="t-meta text-ink-faint">Date</span>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="num-table rounded-inner border border-line bg-surface px-sp-3 py-sp-2 t-body text-ink focus:border-accent focus:outline-none"
            />
          </label>

          <label className="flex flex-col gap-sp-2">
            <span className="t-meta text-ink-faint">Ticker (optional)</span>
            <input
              type="text"
              list="journal-tickers"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="AMD"
              className="w-32 rounded-inner border border-line bg-surface px-sp-3 py-sp-2 t-body text-ink uppercase placeholder:normal-case placeholder:text-ink-faint focus:border-accent focus:outline-none"
            />
            <datalist id="journal-tickers">
              {tickers.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
          </label>

          <Button
            variant="primary"
            size="md"
            onClick={handleSave}
            disabled={saving || !content.trim()}
            className="ml-auto"
          >
            {saving ? "Saving…" : "Save note"}
          </Button>
        </div>

        {error && <p className="t-body text-loss">{error}</p>}
      </div>
    </Card>
  );
}

function EntryCard({ entry, onDelete }: { entry: JournalEntry; onDelete: (id: number) => void }) {
  const name = entry.linked_ticker ? companyName(entry.linked_ticker) : null;
  return (
    <Card tone={entry.linked_ticker ? "accent" : "neutral"}>
      <div className="flex flex-wrap items-start gap-sp-4 px-sp-6 py-sp-5">
        {entry.linked_ticker && <TickerMark ticker={entry.linked_ticker} size="sm" />}
        <div className="min-w-[16rem] flex-1">
          <div className="flex flex-wrap items-center gap-sp-3">
            <span className="num-table t-body font-semibold text-ink">{fmtDate(entry.date)}</span>
            {entry.linked_ticker && (
              <Tag>
                {entry.linked_ticker}
                {name ? ` · ${name}` : ""}
              </Tag>
            )}
          </div>
          <p className="mt-sp-3 max-w-[76ch] t-body whitespace-pre-wrap text-ink-dim">
            {entry.content}
          </p>
        </div>
        <Button
          variant="danger"
          onClick={() => onDelete(entry.id)}
          aria-label={`Delete the note from ${fmtDate(entry.date)}`}
        >
          <Trash size={14} />
          Delete
        </Button>
      </div>
    </Card>
  );
}

/**
 * Freeform notes tied to a date and, optionally, a ticker. Deliberately the
 * plainest screen in the app: a box to write in and a list of what you
 * wrote. The value is in going back and reading what you actually thought
 * before you knew how it turned out, and nothing about that needs structure
 * imposed on it.
 *
 * There is no edit control, by design — see api/routes/journal.py.
 */
export function JournalScreen() {
  const { state, reload, setData } = useAsyncData(
    loadJournalScreen,
    "Unexpected error loading the journal.",
  );
  const entries = state.kind === "loaded" ? state.data.entries : [];
  const tickers = state.kind === "loaded" ? state.data.tickers : [];

  async function handleDelete(id: number) {
    if (!window.confirm("Delete this note? It can't be recovered.")) return;
    await deleteJournalEntry(id);
    setData((prev) => ({ ...prev, entries: prev.entries.filter((e) => e.id !== id) }));
  }

  function handleSaved(entry: JournalEntry) {
    setData((prev) => ({
      ...prev,
      entries: [entry, ...prev.entries].sort((a, b) =>
        a.date < b.date ? 1 : a.date > b.date ? -1 : b.id - a.id,
      ),
    }));
  }

  const linkedCount = entries.filter((e) => e.linked_ticker !== null).length;

  return (
    <ScreenShell
      title="Journal"
      subtitle="What you were thinking at the time, in your own words."
    >
      {state.kind === "loading" && <LoadingSkeleton />}
      {state.kind === "error" && <ErrorPanel message={state.message} onRetry={reload} />}

      {state.kind === "loaded" && (
        <>
          <Section title="New note">
            <Composer tickers={tickers} onSaved={handleSaved} />
          </Section>

          <Section
            title="Entries"
            count={entries.length}
            icon={<Notebook size={19} weight="fill" className="text-accent" />}
            subtitle={
              entries.length > 0
                ? `${linkedCount} of ${entries.length} tied to a specific name.`
                : undefined
            }
          >
            {entries.length === 0 ? (
              <EmptyRow
                label="Nothing written yet."
                hint="Write down why you acted, or why you didn't. It's worth more later than it feels now."
              />
            ) : (
              <div className="flex flex-col gap-sp-4">
                {entries.map((e, i) => (
                  <div
                    key={e.id}
                    className="animate-rise"
                    style={{ "--stagger-index": Math.min(i, 6) } as React.CSSProperties}
                  >
                    <EntryCard entry={e} onDelete={handleDelete} />
                  </div>
                ))}
              </div>
            )}
          </Section>
        </>
      )}
    </ScreenShell>
  );
}
