import { Route, HashRouter, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { BriefingScreen } from "./routes/BriefingScreen";
import { PositionsScreen } from "./routes/PositionsScreen";
import { OrdersScreen } from "./routes/OrdersScreen";
import { InsightsScreen } from "./routes/InsightsScreen";
import { PerformanceScreen } from "./routes/PerformanceScreen";
import { JournalScreen } from "./routes/JournalScreen";
import { SettingsScreen } from "./routes/SettingsScreen";

export default function App() {
  return (
    <HashRouter>
      <div className="flex h-dvh bg-canvas">
        <Sidebar />
        <main className="min-w-0 flex-1">
          <Routes>
            <Route path="/" element={<BriefingScreen />} />
            <Route path="/positions" element={<PositionsScreen />} />
            <Route path="/orders" element={<OrdersScreen />} />
            <Route path="/insights" element={<InsightsScreen />} />
            <Route path="/performance" element={<PerformanceScreen />} />
            <Route path="/journal" element={<JournalScreen />} />
            <Route path="/settings" element={<SettingsScreen />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  );
}
