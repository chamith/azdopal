import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { get, post } from "../api";
import type { SummaryRow } from "../api";

export default function SprintSummary({ period, team }: { period: string; team: string }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [includeCommits, setIncludeCommits] = useState(false);
  const queryClient = useQueryClient();

  const handleSync = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const syncPrsOnly = !includeCommits;
      const res = await post<{ message: string }>("/api/sync-code", {
        period,
        team,
        sync_prs_only: String(syncPrsOnly),
      });
      setSyncMsg(res.message);
      queryClient.invalidateQueries({ queryKey: ["summary", period, team] });
    } catch (e: unknown) {
      setSyncMsg(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const { data = [], isLoading, error } = useQuery<SummaryRow[]>({
    queryKey: ["summary", period, team],
    queryFn: () => get("/api/summary", { period, team }),
    enabled: !!period,
  });

  if (!period) return <p className="empty">Select a sprint to get started.</p>;

  const header = (
    <h2 className="page-title">
      Code — <span className="period">{period}</span>
      {team && <span className="team-badge">{team}</span>}
      <button className="sync-btn" onClick={handleSync} disabled={syncing || !period}>
        {syncing ? "Syncing…" : "⟳ Sync"}
      </button>
      <label className="sync-toggle">
        <input
          type="checkbox"
          checked={includeCommits}
          onChange={(e) => setIncludeCommits(e.target.checked)}
          disabled={syncing}
        />
        Include Commits
      </label>
      {syncMsg && <span className="sync-msg">{syncMsg}</span>}
    </h2>
  );

  if (isLoading) return <div>{header}<p className="loading">Loading…</p></div>;
  if (error) return <div>{header}<p className="error">Failed to load data.</p></div>;
  if (!data.length) return <div>{header}<p className="empty">No data for this period. Try syncing.</p></div>;

  const totalCommits = data.reduce((s, r) => s + r.commits, 0);
  const totalPRs = data.reduce((s, r) => s + r.prs, 0);

  function goToEngineer(email: string) {
    const p = new URLSearchParams(params);
    navigate(`/engineer/${encodeURIComponent(email)}?${p}`);
  }

  return (
    <div>
      {header}
      <div className="stat-cards">
        <div className="stat-card"><div className="stat-value">{data.length}</div><div className="stat-label">Engineers</div></div>
        <div className="stat-card"><div className="stat-value">{totalCommits}</div><div className="stat-label">Commits</div></div>
        <div className="stat-card"><div className="stat-value">{totalPRs}</div><div className="stat-label">PRs</div></div>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Engineer</th>
            <th className="num">Commits</th>
            <th className="num">PRs</th>
            <th className="num">Avg Review</th>
          </tr>
        </thead>
        <tbody>
          {data.sort((a, b) => b.commits - a.commits).map(row => (
            <tr key={row.engineer} className="clickable" onClick={() => goToEngineer(row.engineer)}>
              <td>{row.engineer}</td>
              <td className="num">{row.commits}</td>
              <td className="num">{row.prs}</td>
              <td className="num">{row.avg_review_hours != null ? `${row.avg_review_hours.toFixed(1)}h` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
