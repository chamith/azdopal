import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "../api";
import type { WorkItem } from "../api";

interface WorkItemWithChildren extends WorkItem {
  parent_id: number | null;
  activated_date: string | null;
  sprints_active: number | null;
  spilled_from: string | null;
  children: WorkItemWithChildren[];
}

function buildHierarchy(items: WorkItemWithChildren[]): WorkItemWithChildren[] {
  const map = new Map<number, WorkItemWithChildren>();
  items.forEach(i => map.set(i.id, { ...i, children: [] }));
  const roots: WorkItemWithChildren[] = [];
  map.forEach(item => {
    if (item.parent_id && map.has(item.parent_id)) {
      map.get(item.parent_id)!.children.push(item);
    } else if (item.type !== "Task") {
      // Only show non-Task items as roots (orphaned tasks are hidden)
      roots.push(item);
    } else if (!item.parent_id) {
      // Tasks with no parent at all are shown as roots
      roots.push(item);
    }
    // Tasks with a parent_id that's not in the data are hidden
  });
  return roots;
}

/** Check if an item or any of its children match the engineer filter */
function matchesEngineer(wi: WorkItemWithChildren, eng: string): boolean {
  if (wi.engineer_email === eng) return true;
  return wi.children.some(child => matchesEngineer(child, eng));
}

function WICard({ wi, depth = 0 }: { wi: WorkItemWithChildren; depth?: number }) {
  const [collapsed, setCollapsed] = useState(depth === 0 && wi.children.length > 0);
  const hasChildren = wi.children.length > 0;

  return (
    <div style={{ marginLeft: depth * 20 }}>
      <div className="wi-card">
        <div className="wi-header">
          {hasChildren && (
            <button className="collapse-btn" onClick={() => setCollapsed(!collapsed)}>
              {collapsed ? "▶" : "▼"}
            </button>
          )}
          {!hasChildren && <span className="collapse-spacer" />}
          <span className="badge badge-type">{wi.type}</span>
          <span className="badge badge-state">{wi.state}</span>
          <span className="wi-id">#{wi.id}</span>
          <a href={wi.url} target="_blank" rel="noreferrer" className="wi-title">{wi.title}</a>
          {wi.spilled_from && <span className="badge badge-spilled">Spilled from {wi.spilled_from}</span>}
          {hasChildren && <span className="child-count">{wi.children.length} child{wi.children.length > 1 ? "ren" : ""}</span>}
        </div>
        <div className="wi-meta">
          <span className="wi-owner">{wi.engineer_email}</span>
          {wi.story_points != null && <span>SP: {wi.story_points}</span>}
          {wi.original_estimate != null && <span>Est: {wi.original_estimate}h</span>}
          {wi.completed_work != null && <span>Done: {wi.completed_work}h</span>}
          {wi.remaining_work != null && <span>Rem: {wi.remaining_work}h</span>}
          {wi.activated_date && <span>Active since: {wi.activated_date.slice(0, 10)}</span>}
          {wi.sprints_active != null && wi.sprints_active >= 1 && (
            <span className={`sprints-active ${wi.sprints_active > 2 ? "warn" : ""}`}>
              {wi.sprints_active} sprint{wi.sprints_active > 1 ? "s" : ""}
            </span>
          )}
          <span className="wi-date">{wi.changed_date?.slice(0, 10)}</span>
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
      {!collapsed && wi.children.map(child => (
        <WICard key={child.id} wi={child} depth={depth + 1} />
      ))}
    </div>
  );
}

export default function WorkItems({ period, team }: { period: string; team: string }) {
  const [filterState, setFilterState] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterEng, setFilterEng] = useState("");
  const [filterSpilled, setFilterSpilled] = useState("");
  const [filterSprints, setFilterSprints] = useState("");

  const { data = [], isLoading, error } = useQuery<WorkItem[]>({
    queryKey: ["work-items", period, team],
    queryFn: () => get("/api/work-items", { period, team }),
    enabled: !!period,
  });

  if (!period) return <p className="empty">Select a sprint to get started.</p>;
  if (isLoading) return <p className="loading">Loading…</p>;
  if (error) return <p className="error">Failed to load work items.</p>;

  const allItems = data as WorkItemWithChildren[];
  const types = ["User Story", "Bug"];
  const states = [...new Set(allItems.map(w => w.state))].sort();
  const engineers = [...new Set(allItems.map(w => w.engineer_email))].sort();

  // Apply state and type filters to root items only, keep Task children
  const preFiltered = allItems.filter(w => {
    // Only Tasks are treated as children that bypass filters
    if (w.type === "Task" && w.parent_id && allItems.some(p => p.id === w.parent_id)) {
      return true;
    }
    return (!filterState || w.state === filterState) &&
           (!filterType || w.type === filterType);
  });

  // Build hierarchy from all pre-filtered items
  const tree = buildHierarchy(preFiltered);

  // Apply engineer filter on the tree — show a root if it or any child matches
  let filteredTree = filterEng
    ? tree.filter(wi => matchesEngineer(wi, filterEng))
    : [...tree];

  // Apply spilled filter
  if (filterSpilled === "spilled") {
    filteredTree = filteredTree.filter(wi => wi.spilled_from);
  } else if (filterSpilled === "not-spilled") {
    filteredTree = filteredTree.filter(wi => !wi.spilled_from);
  }

  // Apply sprint span filter
  if (filterSprints) {
    const n = parseInt(filterSprints);
    if (filterSprints === "4+") {
      filteredTree = filteredTree.filter(wi => wi.sprints_active != null && wi.sprints_active >= 4);
    } else if (!isNaN(n)) {
      filteredTree = filteredTree.filter(wi => wi.sprints_active === n);
    }
  }

  // Sort: User Stories first, then Bugs
  filteredTree.sort((a, b) => {
    const order: Record<string, number> = { "User Story": 0, "Bug": 1 };
    return (order[a.type] ?? 2) - (order[b.type] ?? 2);
  });

  const itemCount = filteredTree.length;

  // Summary counts by status for stories and bugs only
  const summaryMap: Record<string, { stories: number; bugs: number }> = {};
  for (const wi of filteredTree) {
    const status = wi.state;
    if (!summaryMap[status]) summaryMap[status] = { stories: 0, bugs: 0 };
    if (wi.type === "User Story") summaryMap[status].stories++;
    else if (wi.type === "Bug") summaryMap[status].bugs++;
  }
  const summaryRows = Object.entries(summaryMap).sort((a, b) => a[0].localeCompare(b[0]));
  const totalStories = summaryRows.reduce((s, [, v]) => s + v.stories, 0);
  const totalBugs = summaryRows.reduce((s, [, v]) => s + v.bugs, 0);

  return (
    <div>
      <h2 className="page-title">
        Work Items — <span className="period">{period}</span>
        {team && <span className="team-badge">{team}</span>}
      </h2>

      <div className="filter-bar">
        <select value={filterEng} onChange={e => setFilterEng(e.target.value)}>
          <option value="">All engineers</option>
          {engineers.map(e => <option key={e} value={e}>{e}</option>)}
        </select>
        <select value={filterType} onChange={e => setFilterType(e.target.value)}>
          <option value="">All types</option>
          {types.map(t => <option key={t}>{t}</option>)}
        </select>
        <select value={filterState} onChange={e => setFilterState(e.target.value)}>
          <option value="">All states</option>
          {states.map(s => <option key={s}>{s}</option>)}
        </select>
        <select value={filterSpilled} onChange={e => setFilterSpilled(e.target.value)}>
          <option value="">All items</option>
          <option value="spilled">Spilled only</option>
          <option value="not-spilled">Not spilled</option>
        </select>
        <select value={filterSprints} onChange={e => setFilterSprints(e.target.value)}>
          <option value="">Any sprint span</option>
          <option value="1">1 sprint</option>
          <option value="2">2 sprints</option>
          <option value="3">3 sprints</option>
          <option value="4+">4+ sprints</option>
        </select>
        <span className="filter-count">{itemCount} items</span>
      </div>

      <table className="data-table summary-table">
        <thead>
          <tr>
            <th>Type</th>
            {summaryRows.map(([status]) => (
              <th key={status} className="num"><span className="badge badge-state">{status}</span></th>
            ))}
            <th className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Stories</td>
            {summaryRows.map(([status, counts]) => (
              <td key={status} className="num">{counts.stories || "—"}</td>
            ))}
            <td className="num"><strong>{totalStories}</strong></td>
          </tr>
          <tr>
            <td>Bugs</td>
            {summaryRows.map(([status, counts]) => (
              <td key={status} className="num">{counts.bugs || "—"}</td>
            ))}
            <td className="num"><strong>{totalBugs}</strong></td>
          </tr>
        </tbody>
      </table>

      <div className="wi-list">
        {filteredTree.map(wi => <WICard key={wi.id} wi={wi} />)}
      </div>
      {!filteredTree.length && <p className="empty">No work items match the current filters.</p>}
    </div>
  );
}
