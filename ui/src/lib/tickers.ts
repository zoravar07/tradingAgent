/**
 * Ticker → company name, for the identity line under a ticker on a trade or
 * position card (the reference sets "Advanced Micro Devices" under "AMD").
 *
 * These are facts about the instruments, not data about the portfolio — the
 * database stores tickers only, and there is no name field to read. Covers
 * every symbol currently in the book plus the index funds held alongside
 * them; anything not listed renders with no subtitle rather than a guess.
 */
const COMPANY_NAMES: Record<string, string> = {
  AMD: "Advanced Micro Devices",
  CEG: "Constellation Energy",
  CLS: "Celestica",
  CRDO: "Credo Technology Group",
  IAU: "iShares Gold Trust",
  MP: "MP Materials",
  MRVL: "Marvell Technology",
  MSFT: "Microsoft",
  NBIS: "Nebius Group",
  NVDA: "NVIDIA",
  PLTR: "Palantir Technologies",
  RKLB: "Rocket Lab",
  SOFI: "SoFi Technologies",
  VGT: "Vanguard Information Technology ETF",
  VRT: "Vertiv Holdings",
  VTI: "Vanguard Total Stock Market ETF",
};

export function companyName(ticker: string): string | null {
  return COMPANY_NAMES[ticker.toUpperCase()] ?? null;
}
