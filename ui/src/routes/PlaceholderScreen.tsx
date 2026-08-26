import type { Icon } from "@phosphor-icons/react";

export function PlaceholderScreen({ title, icon: Icon }: { title: string; icon: Icon }) {
  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-[var(--color-hairline)] px-8 py-5">
        <h1 className="text-lg font-semibold text-[var(--color-ink)]">{title}</h1>
      </header>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
        <Icon size={26} className="text-[var(--color-ink-faint)]" />
        <p className="text-sm text-[var(--color-ink-dim)]">{title} isn't built yet.</p>
      </div>
    </div>
  );
}
