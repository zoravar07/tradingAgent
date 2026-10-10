import { WarningCircle, ArrowClockwise } from "@phosphor-icons/react";
import { Button } from "./ui/Button";

export function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-sp-3 rounded-card border border-line bg-inset px-sp-6 py-sp-8 text-center">
      <WarningCircle size={28} className="text-loss" />
      <p className="t-title text-ink">Couldn't load this screen</p>
      <p className="max-w-[52ch] t-body text-ink-dim">{message}</p>
      <Button onClick={onRetry} className="mt-sp-2">
        <ArrowClockwise size={14} />
        Retry
      </Button>
    </div>
  );
}
