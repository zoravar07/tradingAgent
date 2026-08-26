import { Route, HashRouter, Routes } from "react-router-dom";
import { ChartPieSlice, ClockCounterClockwise, GearSix, MagnifyingGlass } from "@phosphor-icons/react";
import { Sidebar } from "./components/Sidebar";
import { BriefingScreen } from "./routes/BriefingScreen";
import { PlaceholderScreen } from "./routes/PlaceholderScreen";

export default function App() {
  return (
    <HashRouter>
      <div className="flex h-dvh bg-[var(--color-ground)]">
        <Sidebar />
        <main className="min-w-0 flex-1">
          <Routes>
            <Route path="/" element={<BriefingScreen />} />
            <Route
              path="/positions"
              element={<PlaceholderScreen title="Positions" icon={ChartPieSlice} />}
            />
            <Route
              path="/research"
              element={<PlaceholderScreen title="Research" icon={MagnifyingGlass} />}
            />
            <Route
              path="/history"
              element={<PlaceholderScreen title="History" icon={ClockCounterClockwise} />}
            />
            <Route path="/settings" element={<PlaceholderScreen title="Settings" icon={GearSix} />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  );
}
