import { NavLink } from "react-router-dom";
import {
  NewspaperClipping,
  ChartPieSlice,
  MagnifyingGlass,
  ClockCounterClockwise,
  GearSix,
} from "@phosphor-icons/react";

const NAV_ITEMS: { to: string; label: string; icon: typeof NewspaperClipping; end?: boolean }[] = [
  { to: "/", label: "Briefing", icon: NewspaperClipping, end: true },
  { to: "/positions", label: "Positions", icon: ChartPieSlice },
  { to: "/research", label: "Research", icon: MagnifyingGlass },
  { to: "/history", label: "History", icon: ClockCounterClockwise },
  { to: "/settings", label: "Settings", icon: GearSix },
];

export function Sidebar() {
  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-[var(--color-hairline)] bg-[var(--color-panel)]">
      <div className="flex items-center gap-2 px-5 py-5">
        <span className="h-2 w-2 rounded-full bg-[var(--color-accent)]" />
        <span className="text-sm font-semibold tracking-[0.14em] text-[var(--color-ink)]">
          Z MONEY
        </span>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 px-3">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              [
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-[var(--color-accent-wash)] text-[var(--color-ink)]"
                  : "text-[var(--color-ink-dim)] hover:bg-[var(--color-panel-raised)] hover:text-[var(--color-ink)]",
              ].join(" ")
            }
          >
            {({ isActive }) => (
              <>
                <Icon
                  size={17}
                  weight={isActive ? "fill" : "regular"}
                  color={isActive ? "var(--color-accent)" : "currentColor"}
                />
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-[var(--color-hairline)] px-5 py-4 text-xs text-[var(--color-ink-faint)]">
        Local · single-user
      </div>
    </aside>
  );
}
