export function SectionShell({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-[var(--color-hairline)] bg-[var(--color-panel)]">
      <header className="flex items-center gap-2 border-b border-[var(--color-hairline)] px-4 py-3">
        <h2 className="text-[13px] font-semibold tracking-[0.02em] text-[var(--color-ink)]">
          {title}
        </h2>
        {count !== undefined && (
          <span className="text-[13px] text-[var(--color-ink-faint)]">{count}</span>
        )}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function EmptySection({ label }: { label: string }) {
  return <p className="py-4 text-center text-sm text-[var(--color-ink-faint)]">{label}</p>;
}
