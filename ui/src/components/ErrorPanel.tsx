import { WarningCircle, ArrowClockwise } from "@phosphor-icons/react";

export function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-24 text-center">
      <WarningCircle size={28} className="text-[var(--color-loss)]" />
      <p className="text-sm font-medium text-[var(--color-ink)]">Couldn't load the briefing</p>
      <p className="max-w-sm text-sm text-[var(--color-ink-dim)]">{message}</p>
      <button
        onClick={onRetry}
        className="mt-1 flex items-center gap-1.5 rounded-md border border-[var(--color-hairline-strong)] px-3 py-1.5 text-xs font-medium text-[var(--color-ink)] transition-colors hover:bg-[var(--color-panel-raised)] active:scale-[0.98]"
      >
        <ArrowClockwise size={13} />
        Retry
      </button>
    </div>
  );
}
