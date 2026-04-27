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

/** Toggle a value in a Set — returns a new Set */
function toggle<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

function ChipGroup({ label, options, selected, onToggle }: {
  label: string;
  options: string[];
  selected: Set<string>;
  onToggle: (v: string) => void;
}) {
  return (
    <div className="chip-group">
      <span className="chip-label">{label}:</span>
      {options.map(o => (
        <button
          key={o}
          className={`chip ${selected.has(o) ? "chip-active" : ""}`}
          onClick={() => onToggle(o)}
        >
          {o}
        </button>
      ))}
      {selected.size > 0 && (
        <button className="chip chip-clear" onClick={() => options.forEach(o => { if (selected.has(o)) onToggle(o); })}>
          ✕
        </button>
      )}
    </div>
  );
}

export default function WorkItems({ period, team }: { period: string; team: string }) {
  const [selStates, setSelStates] = useState<Set<string>>(new Set());
  const [selTypes, setSelTypes] = useState<Set<string>>(new Set());
  const [selEngs, setSelEngs] = useState<Set<string>>(new Set());
  const [selSpilled, setSelSpilled] = useState<Set<string>>(new Set());
  const [selSprints, setSelSprints] = useState<Set<string>>(new Set());

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
  const spilledOptions = ["Spilled", "Not spilled"];
  const sprintSpanOptions = ["1 sprint", "2 sprints", "3 sprints", "4+ sprints"];

  // Apply state and type filters to root items only, keep Task children
  const preFiltered = allItems.filter(w => {
    if (w.type === "Task" && w.parent_id && allItems.some(p => p.id === w.parent_id)) {
      return true;
    }
    if (selStates.size > 0 && !selStates.has(w.state)) return false;
    if (selTypes.size > 0 && !selTypes.has(w.type)) return false;
    return true;
  });

  // Build hierarchy
  const tree = buildHierarchy(preFiltered);

  // Apply engineer filter — show root if it or any child matches any selected engineer
  let filteredTree = selEngs.size > 0
    ? tree.filter(wi => [...selEngs].some(eng => matchesEngineer(wi, eng)))
    : [...tree];

  // Apply spilled filter
  if (selSpilled.has("Spilled") && !selSpilled.has("Not spilled")) {
    filteredTree = filteredTree.filter(wi => wi.spilled_from);
  } else if (selSpilled.has("Not spilled") && !selSpilled.has("Spilled")) {
    filteredTree = filteredTree.filter(wi => !wi.spilled_from);
  }

  // Apply sprint span filter
  if (selSprints.size > 0) {
    filteredTree = filteredTree.filter(wi => {
      const s = wi.sprints_active;
      if (s == null) return false;
      for (const sel of selSprints) {
        if (sel === "4+ sprints" && s >= 4) return true;
        const n = parseInt(sel);
        if (!isNaN(n) && s === n) return true;
      }
      return false;
    });
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

      <div className="filter-section">
        <ChipGroup label="Engineer" options={engineers} selected={selEngs}
          onToggle={v => setSelEngs(toggle(selEngs, v))} />
        <ChipGroup label="Type" options={types} selected={selTypes}
          onToggle={v => setSelTypes(toggle(selTypes, v))} />
        <ChipGroup label="State" options={states} selected={selStates}
          onToggle={v => setSelStates(toggle(selStates, v))} />
        <ChipGroup label="Spillover" options={spilledOptions} selected={selSpilled}
          onToggle={v => setSelSpilled(toggle(selSpilled, v))} />
        <ChipGroup label="Sprint span" options={sprintSpanOptions} selected={selSprints}
          onToggle={v => setSelSprints(toggle(selSprints, v))} />
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
