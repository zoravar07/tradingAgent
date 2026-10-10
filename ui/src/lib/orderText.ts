import { fmtPctPlain, fmtUsd, fmtUsd2, shareParts } from "./format";

/**
 * Trade instructions as a person would say them, in one place so every
 * screen phrases them the same way.
 *
 *   "Sell 1 share of AMD at $503.21 (limit order)"
 *   "Buy 12 shares of DELL at $540.20 (limit order)"
 *
 * The supporting context — cost, share of the portfolio, whether it is a
 * partial sell — is a separate sentence, never crammed into the headline.
 */
export interface OrderLike {
  ticker: string;
  action: "BUY" | "SELL";
  quantity: number;
  limit_price: number;
  order_type?: string;
  is_trim?: boolean;
}

export function orderSentence(order: OrderLike): string {
  const verb = order.action === "SELL" ? "Sell" : "Buy";
  const qty = shareParts(order.quantity);
  const type = (order.order_type ?? "LIMIT").toUpperCase() === "LIMIT" ? " (limit order)" : "";
  return `${verb} ${qty.figure} ${qty.unit} of ${order.ticker} at ${fmtUsd2(order.limit_price)}${type}`;
}

export function orderContext(order: OrderLike & { estimated_cost_usd?: number; est_cost?: number; weight_pct?: number | null }): string {
  const cost = order.estimated_cost_usd ?? order.est_cost;
  const parts: string[] = [];
  if (cost !== undefined) {
    const about = `About ${fmtUsd(cost)}`;
    parts.push(order.weight_pct ? `${about}, ${fmtPctPlain(order.weight_pct)} of your portfolio.` : `${about}.`);
  }
  if (order.is_trim) parts.push("A partial sell: you keep the rest of the position.");
  return parts.join(" ");
}
