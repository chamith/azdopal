import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get } from "../api";
import type { Commit, PR, WorkItem } from "../api";

export default function EngineerDetail({ period }: { period: string }) {
  const { email } = useParams<{ email: string }>();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const tab = params.get("tab") || "commits";

  function setTab(t: string) {
    const p = new URLSearchParams(params);
    p.set("tab", t);
    navigate({ search: p.toString() });
  }

  const { data: commits = [], isLoading: lc } = useQuery<Commit[]>({
    queryKey: ["commits", email, period],
    queryFn: () => get(`/api/engineer/${encodeURIComponent(email!)}/commits`, { period }),
    enabled: !!email && !!period && tab === "commits",
  });

  const { data: prs = [], isLoading: lp } = useQuery<PR[]>({
    queryKey: ["prs", email, period],
    queryFn: () => get(`/api/engineer/${encodeURIComponent(email!)}/prs`, { period }),
    enabled: !!email && !!period && tab === "prs",
  });

  const { data: workItems = [], isLoading: lw } = useQuery<WorkItem[]>({
    queryKey: ["work-items-eng", email, period],
    queryFn: () => get(`/api/engineer/${encodeURIComponent(email!)}/work-items`, { period }),
    enabled: !!email && !!period && tab === "work-items",
  });

  return (
    <div>
      <button className="back-btn" onClick={() => navigate(-1)}>← Back</button>
      <h2 className="page-title">{email}</h2>
      <p className="period-label">{period}</p>

      <div className="tabs">
        {["commits", "prs", "work-items"].map(t => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t === "commits" ? "Commits" : t === "prs" ? "Pull Requests" : "Work Items"}
          </button>
        ))}
      </div>

      {tab === "commits" && (
        lc ? <p className="loading">Loading…</p> :
        !commits.length ? <p className="empty">No commits.</p> :
        <table className="data-table">
          <thead><tr><th>Date</th><th>Repo / Branch</th><th>Message</th></tr></thead>
          <tbody>
            {commits.map(c => (
              <tr key={c.url}>
                <td className="date">{c.commit_date?.slice(0, 10)}</td>
                <td className="mono">{c.repo} / {c.branch}</td>
                <td><a href={c.url} target="_blank" rel="noreferrer">{c.message}</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "prs" && (
        lp ? <p className="loading">Loading…</p> :
        !prs.length ? <p className="empty">No PRs.</p> :
        <table className="data-table">
          <thead><tr><th>Date</th><th>Repo</th><th>Title</th><th>Status</th><th className="num">Review</th></tr></thead>
          <tbody>
            {prs.map(pr => (
              <tr key={pr.pr_id}>
                <td className="date">{pr.created_date?.slice(0, 10)}</td>
                <td className="mono">{pr.repo}</td>
                <td><a href={pr.url} target="_blank" rel="noreferrer">{pr.title}</a></td>
                <td><span className={`badge badge-${pr.status}`}>{pr.status}</span></td>
                <td className="num">{pr.review_time_hours != null ? `${pr.review_time_hours.toFixed(1)}h` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "work-items" && (
        lw ? <p className="loading">Loading…</p> :
        !workItems.length ? <p className="empty">No work items.</p> :
        <div className="wi-list">
          {workItems.map(wi => (
            <div key={wi.id} className="wi-card">
              <div className="wi-header">
                <span className={`badge badge-type`}>{wi.type}</span>
                <span className={`badge badge-state`}>{wi.state}</span>
                <span className="wi-id">#{wi.id}</span>
                <a href={wi.url} target="_blank" rel="noreferrer" className="wi-title">{wi.title}</a>
              </div>
              <div className="wi-meta">
                {wi.story_points != null && <span>SP: {wi.story_points}</span>}
                {wi.original_estimate != null && <span>Est: {wi.original_estimate}h</span>}
                {wi.completed_work != null && <span>Done: {wi.completed_work}h</span>}
                {wi.remaining_work != null && <span>Rem: {wi.remaining_work}h</span>}
              </div>
              {wi.linked_prs.length > 0 && (
                <div className="wi-prs">
                  {wi.linked_prs.map(pr => (
                    <a key={pr.pr_id} href={pr.url} target="_blank" rel="noreferrer" className="pr-link">
                      PR #{pr.pr_id} [{pr.repo}]
                    </a>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
