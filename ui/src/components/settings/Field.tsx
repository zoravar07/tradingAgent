import type { ReactNode } from "react";

function FieldWrapper({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs text-[var(--color-ink-dim)]">{label}</span>
      {children}
      {error && <span className="text-xs text-[var(--color-loss)]">{error}</span>}
    </label>
  );
}

const inputClasses = (hasError: boolean) =>
  [
    "num rounded-md border bg-[var(--color-panel-raised)] px-2.5 py-1.5 text-sm text-[var(--color-ink)]",
    "outline-none transition-colors focus:border-[var(--color-accent)]",
    hasError ? "border-[var(--color-loss)]" : "border-[var(--color-hairline-strong)]",
  ].join(" ");

export function NumberField({
  label,
  value,
  onChange,
  error,
  step,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  error?: string;
  step?: number;
}) {
  return (
    <FieldWrapper label={label} error={error}>
      <input
        type="number"
        step={step ?? "any"}
        value={value}
        onChange={(e) => onChange(e.target.valueAsNumber)}
        className={inputClasses(!!error)}
      />
    </FieldWrapper>
  );
}

export function TextField({
  label,
  value,
  onChange,
  error,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  error?: string;
  placeholder?: string;
}) {
  return (
    <FieldWrapper label={label} error={error}>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={`${inputClasses(!!error)} font-mono`}
      />
    </FieldWrapper>
  );
}

export function CheckboxField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2.5 py-1.5">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[var(--color-accent)]"
      />
      <span className="text-sm text-[var(--color-ink)]">{label}</span>
    </label>
  );
}
