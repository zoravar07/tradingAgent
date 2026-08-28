import { Route, HashRouter, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { BriefingScreen } from "./routes/BriefingScreen";
import { PositionsScreen } from "./routes/PositionsScreen";
import { ResearchScreen } from "./routes/ResearchScreen";
import { HistoryScreen } from "./routes/HistoryScreen";
import { SettingsScreen } from "./routes/SettingsScreen";

export default function App() {
  return (
    <HashRouter>
      <div className="flex h-dvh bg-[var(--color-ground)]">
        <Sidebar />
        <main className="min-w-0 flex-1">
          <Routes>
            <Route path="/" element={<BriefingScreen />} />
            <Route path="/positions" element={<PositionsScreen />} />
            <Route path="/research" element={<ResearchScreen />} />
            <Route path="/history" element={<HistoryScreen />} />
            <Route path="/settings" element={<SettingsScreen />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  );
}
