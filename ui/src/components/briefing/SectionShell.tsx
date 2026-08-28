import type { Icon } from "@phosphor-icons/react";

export function SectionShell({
  title,
  subtitle,
  count,
  accent,
  icon: TitleIcon,
  children,
}: {
  title: string;
  subtitle?: string;
  count?: number;
  /** Stronger border/header treatment for the section that matters most on the page. */
  accent?: boolean;
  icon?: Icon;
  children: React.ReactNode;
}) {
  return (
    <section
      className={`rounded-xl border bg-[var(--color-panel)] ${
        accent ? "border-[var(--color-accent)]/30" : "border-[var(--color-hairline)]"
      }`}
    >
      <header
        className={`flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b px-4 py-3 ${
          accent ? "border-[var(--color-accent)]/20" : "border-[var(--color-hairline)]"
        }`}
      >
        {TitleIcon && <TitleIcon size={15} weight="bold" className="text-[var(--color-ink-faint)]" />}
        <h2 className="text-[13px] font-semibold tracking-[0.02em] text-[var(--color-ink)]">{title}</h2>
        {count !== undefined && <span className="text-[13px] text-[var(--color-ink-faint)]">{count}</span>}
        {subtitle && <span className="w-full text-xs text-[var(--color-ink-faint)]">{subtitle}</span>}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function EmptySection({ label }: { label: string }) {
  return <p className="py-4 text-center text-sm text-[var(--color-ink-faint)]">{label}</p>;
}
