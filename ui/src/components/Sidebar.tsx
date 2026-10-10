import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import {
  ChartBar,
  ChartLineUp,
  GearSix,
  Lightbulb,
  NotePencil,
  Notebook,
  Question,
  Receipt,
  type Icon,
} from "@phosphor-icons/react";
import { formatCountdown, marketStatus } from "../lib/marketHours";

/**
 * Nav order is the reading order of the product: what to do today, what
 * might need doing soon, what you hold, what you've done, why you hold it,
 * how it's gone, what you thought at the time, and finally the machinery.
 */
const NAV_ITEMS: { to: string; label: string; icon: Icon; end?: boolean }[] = [
  { to: "/", label: "Briefing", icon: NotePencil, end: true },
  { to: "/positions", label: "Positions", icon: ChartBar },
  { to: "/orders", label: "Proposals", icon: Receipt },
  { to: "/insights", label: "Insights", icon: Lightbulb },
  { to: "/performance", label: "Performance", icon: ChartLineUp },
  { to: "/journal", label: "Journal", icon: Notebook },
  { to: "/settings", label: "Settings", icon: GearSix },
];

/**
 * The reference's session readout. It ticks once a second, which is the one
 * number in the app that is allowed to move: it is a countdown, so a static
 * value would simply be wrong a second later.
 */
function MarketStatusPanel() {
  const [status, setStatus] = useState(() => marketStatus());

  useEffect(() => {
    const id = setInterval(() => setStatus(marketStatus()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="rounded-inner border border-line bg-surface px-sp-4 py-sp-3">
      <div className="flex items-center gap-sp-2">
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${status.open ? "bg-gain" : "bg-ink-faint"}`}
        />
        <span className={`t-body font-medium ${status.open ? "text-gain" : "text-ink-dim"}`}>
          {status.open ? "Market is open" : "Market is closed"}
        </span>
      </div>
      <p className="mt-sp-1 num-table t-meta text-ink-faint">
        {status.open ? "Closes in" : "Opens in"} {formatCountdown(status.secondsUntilChange)}
      </p>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="flex h-full w-[248px] shrink-0 flex-col border-r border-line bg-rail">
      <div className="flex items-center gap-sp-3 px-sp-5 py-sp-6">
        <img src="/favicon.svg" alt="" className="h-6 w-6" aria-hidden />
        <span className="t-title tracking-tight text-ink">Z Money</span>
      </div>

      <nav className="flex flex-1 flex-col gap-[2px] px-sp-3">
        {NAV_ITEMS.map(({ to, label, icon: ItemIcon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              [
                "flex items-center gap-sp-3 rounded-inner px-sp-3 py-sp-3 t-body transition-colors duration-[var(--dur-hover)]",
                isActive
                  ? "bg-inset-strong font-semibold text-ink"
                  : "font-medium text-ink-dim hover:bg-inset hover:text-ink",
              ].join(" ")
            }
          >
            {({ isActive }) => (
              <>
                <ItemIcon size={19} weight={isActive ? "fill" : "regular"} />
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="flex flex-col gap-sp-3 px-sp-4 pb-sp-4">
        <MarketStatusPanel />
        <div className="flex items-center gap-sp-3 px-sp-2 py-sp-2 t-body text-ink-faint">
          <Question size={19} />
          Local · single-user
        </div>
      </div>
    </aside>
  );
}
