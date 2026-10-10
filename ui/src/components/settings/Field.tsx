import type { ReactNode } from "react";

function FieldWrapper({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-sp-2">
      <span className="t-meta text-ink-dim">{label}</span>
      {children}
      {error && <span className="t-meta text-loss">{error}</span>}
    </label>
  );
}

const inputClasses = (hasError: boolean) =>
  [
    "num-table rounded-inner border bg-surface px-sp-3 py-sp-2 t-body text-ink",
    "outline-none transition-colors duration-[var(--dur-hover)] focus:border-accent",
    hasError ? "border-loss" : "border-line",
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
        className={`${inputClasses(!!error)} placeholder:text-ink-faint`}
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
    <label className="flex items-center gap-sp-3 py-sp-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[var(--color-accent)]"
      />
      <span className="t-body text-ink">{label}</span>
    </label>
  );
}
