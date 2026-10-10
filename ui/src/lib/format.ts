export function fmtUsd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function fmtUsd2(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
}

export function fmtPct(n: number, digits = 1): string {
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

/** Unsigned — for magnitudes where a "+" would be meaningless (a weight, a
 * drawdown, a distance to a trigger). */
export function fmtPctPlain(n: number, digits = 1): string {
  return `${n.toFixed(digits)}%`;
}

export function fmtNum(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

/**
 * Quantity split into figure and unit so a card can set them at different
 * sizes — the reference renders "1" at stat size and "share" at label size,
 * on one baseline.
 *
 * The unit is spelled out. "1 sh" saved four characters and cost the reader
 * a beat working out what "sh" meant; nothing on these screens is tight
 * enough to need the abbreviation.
 */
export function shareParts(qty: number): { figure: string; unit: string } {
  return {
    figure: fmtNum(qty),
    unit: qty === 1 ? "share" : "shares",
  };
}

/** The same value as one string, for places with no room for two spans. */
export function fmtShares(qty: number): string {
  const { figure, unit } = shareParts(qty);
  return `${figure} ${unit}`;
}

export function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** "Aug 27, 2026" — the form used on cards and timeline headers. */
export function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** "Saturday, August 31, 2026" — the header form in the reference. */
export function fmtLongDate(d: Date): string {
  return d.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

/** Sentence-case time of day, for the greeting. */
export function greetingFor(d: Date): string {
  const h = d.getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}
