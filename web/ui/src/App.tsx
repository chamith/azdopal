import { Routes, Route, NavLink, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get } from "./api";
import type { Sprint, Team } from "./api";
import SprintSummary from "./pages/SprintSummary";
import EngineerDetail from "./pages/EngineerDetail";
import WorkItems from "./pages/WorkItems";
import "./App.css";

export default function App() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const { data: sprints = [] } = useQuery<Sprint[]>({
    queryKey: ["sprints"],
    queryFn: () => get("/api/sprints"),
  });

  const { data: teams = [] } = useQuery<Team[]>({
    queryKey: ["teams"],
    queryFn: () => get("/api/teams"),
  });

  const period = params.get("period") || sprints[0]?.name || "";
  const team = params.get("team") || "";

  function setParam(key: string, value: string) {
    const p = new URLSearchParams(params);
    p.set(key, value);
    navigate({ search: p.toString() });
  }

  return (
    <div className="app">
      <header className="header">
        <span className="logo">azdopal</span>
        <nav className="nav">
          <NavLink to={`/code?${params}`}>Code</NavLink>
          <NavLink to={`/work-items?${params}`}>Work Items</NavLink>
        </nav>
        <div className="filters">
          <select value={period} onChange={e => setParam("period", e.target.value)}>
            <option value="">— select sprint —</option>
            {sprints.map(s => (
              <option key={s.name} value={s.name}>
                {s.name}{s.time_frame === "current" ? " (current)" : ""}
              </option>
            ))}
          </select>
          <select value={team} onChange={e => setParam("team", e.target.value)}>
            <option value="">All teams</option>
            {teams.map(t => (
              <option key={t.id} value={t.name}>{t.name}</option>
            ))}
          </select>
        </div>
      </header>

      <main className="main">
        <Routes>
          <Route path="/" element={<SprintSummary period={period} team={team} />} />
          <Route path="/code" element={<SprintSummary period={period} team={team} />} />
          <Route path="/engineer/:email" element={<EngineerDetail period={period} />} />
          <Route path="/work-items" element={<WorkItems period={period} team={team} />} />
        </Routes>
      </main>
    </div>
  );
}
