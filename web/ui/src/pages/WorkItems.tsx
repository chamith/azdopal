import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "../api";
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

  // Roll up hours from children for parent items
  const childCompleted = hasChildren
    ? wi.children.reduce((s, c) => s + (c.completed_work ?? 0), 0)
    : null;
  const childRemaining = hasChildren
    ? wi.children.reduce((s, c) => s + (c.remaining_work ?? 0), 0)
    : null;

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
          {hasChildren && childCompleted != null && <span>Done: {childCompleted}h</span>}
          {hasChildren && childRemaining != null && <span>Rem: {childRemaining}h</span>}
          {!hasChildren && wi.completed_work != null && <span>Done: {wi.completed_work}h</span>}
          {!hasChildren && wi.remaining_work != null && <span>Rem: {wi.remaining_work}h</span>}
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

function ChipGroup({ label, options, selected, onToggle, counts }: {
  label: string;
  options: string[];
  selected: Set<string>;
  onToggle: (v: string) => void;
  counts?: Map<string, number>;
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
          {o}{counts ? ` (${counts.get(o) ?? 0})` : ""}
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
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleSync = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const res = await post<{ synced: number; message: string }>(
        "/api/sync-work-items", { period, team }
      );
      setSyncMsg(res.message);
      queryClient.invalidateQueries({ queryKey: ["work-items", period, team] });
    } catch (e: unknown) {
      setSyncMsg(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const { data = [], isLoading, error } = useQuery<WorkItem[]>({
    queryKey: ["work-items", period, team],
    queryFn: () => get("/api/work-items", { period, team }),
    enabled: !!period,
  });

  const { data: capacityData } = useQuery<{
    total_capacity_hours: number;
    members?: { email: string; capacity_hours: number }[];
  }>({
    queryKey: ["capacity", period, team],
    queryFn: () => get("/api/capacity", { period, team }),
    enabled: !!period && !!team,
  });

  // Calculate capacity filtered by selected engineers
  const filteredCapacity = (() => {
    if (!capacityData) return null;
    if (selEngs.size === 0) return capacityData.total_capacity_hours;
    if (!capacityData.members || capacityData.members.length === 0) return capacityData.total_capacity_hours;
    // Sum capacity for selected engineers only
    let sum = 0;
    for (const m of capacityData.members) {
      if (selEngs.has(m.email)) {
        sum += m.capacity_hours;
      }
    }
    return sum;
  })();

  if (!period) return <p className="empty">Select a sprint to get started.</p>;
  if (isLoading) return <p className="loading">Loading…</p>;
  if (error) return <p className="error">Failed to load work items.</p>;

  const allItems = data as WorkItemWithChildren[];
  const types = ["User Story", "Bug"];
  const states = [...new Set(allItems.map(w => w.state))].sort();
  const engineers = [...new Set(allItems.map(w => w.engineer_email))].sort();
  const spilledOptions = ["Spilled", "Not spilled"];
  const sprintSpanOptions = ["1 sprint", "2 sprints", "3 sprints", "4+ sprints"];

  // Build unfiltered hierarchy for filter options
  const allRoots = buildHierarchy(allItems as WorkItemWithChildren[]);

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

  // Compute counts per filter option from the filtered results
  // For each filter dimension, count against items filtered by all *other* dimensions
  // so selecting "Active" updates engineer/type/spillover/sprint counts but not state counts.
  const countBase = (skipFilter: string) => {
    let items = [...allRoots];
    if (skipFilter !== "type" && selTypes.size > 0)
      items = items.filter(wi => selTypes.has(wi.type));
    if (skipFilter !== "state" && selStates.size > 0)
      items = items.filter(wi => selStates.has(wi.state));
    if (skipFilter !== "engineer" && selEngs.size > 0)
      items = items.filter(wi => [...selEngs].some(eng => matchesEngineer(wi, eng)));
    if (skipFilter !== "spilled") {
      if (selSpilled.has("Spilled") && !selSpilled.has("Not spilled"))
        items = items.filter(wi => wi.spilled_from);
      else if (selSpilled.has("Not spilled") && !selSpilled.has("Spilled"))
        items = items.filter(wi => !wi.spilled_from);
    }
    if (skipFilter !== "sprints" && selSprints.size > 0) {
      items = items.filter(wi => {
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
    return items;
  };

  const engCounts = new Map<string, number>();
  for (const wi of countBase("engineer"))
    engCounts.set(wi.engineer_email, (engCounts.get(wi.engineer_email) ?? 0) + 1);

  const typeCounts = new Map<string, number>();
  for (const wi of countBase("type"))
    typeCounts.set(wi.type, (typeCounts.get(wi.type) ?? 0) + 1);

  const stateCounts = new Map<string, number>();
  for (const wi of countBase("state"))
    stateCounts.set(wi.state, (stateCounts.get(wi.state) ?? 0) + 1);

  const spilledCounts = new Map<string, number>([["Spilled", 0], ["Not spilled", 0]]);
  for (const wi of countBase("spilled")) {
    if (wi.spilled_from) spilledCounts.set("Spilled", spilledCounts.get("Spilled")! + 1);
    else spilledCounts.set("Not spilled", spilledCounts.get("Not spilled")! + 1);
  }

  const sprintSpanCounts = new Map<string, number>();
  for (const o of sprintSpanOptions) sprintSpanCounts.set(o, 0);
  for (const wi of countBase("sprints")) {
    const s = wi.sprints_active;
    if (s != null) {
      if (s >= 4) sprintSpanCounts.set("4+ sprints", sprintSpanCounts.get("4+ sprints")! + 1);
      else if (s === 3) sprintSpanCounts.set("3 sprints", sprintSpanCounts.get("3 sprints")! + 1);
      else if (s === 2) sprintSpanCounts.set("2 sprints", sprintSpanCounts.get("2 sprints")! + 1);
      else if (s === 1) sprintSpanCounts.set("1 sprint", sprintSpanCounts.get("1 sprint")! + 1);
    }
  }

  // Sort: User Stories first, then Bugs
  filteredTree.sort((a, b) => {
    const order: Record<string, number> = { "User Story": 0, "Bug": 1 };
    return (order[a.type] ?? 2) - (order[b.type] ?? 2);
  });

  const itemCount = filteredTree.length;

  // Summary counts by status for stories and bugs only
  const summaryMap: Record<string, { stories: number; bugs: number; remaining: number; completed: number }> = {};
  for (const wi of filteredTree) {
    const status = wi.state;
    if (!summaryMap[status]) summaryMap[status] = { stories: 0, bugs: 0, remaining: 0, completed: 0 };
    if (wi.type === "User Story") summaryMap[status].stories++;
    else if (wi.type === "Bug") summaryMap[status].bugs++;
    summaryMap[status].remaining += wi.remaining_work ?? 0;
    summaryMap[status].completed += wi.completed_work ?? 0;
    // Also sum children's hours
    for (const child of wi.children) {
      summaryMap[status].remaining += child.remaining_work ?? 0;
      summaryMap[status].completed += child.completed_work ?? 0;
    }
  }
  const summaryRows = Object.entries(summaryMap).sort((a, b) => a[0].localeCompare(b[0]));
  const totalStories = summaryRows.reduce((s, [, v]) => s + v.stories, 0);
  const totalBugs = summaryRows.reduce((s, [, v]) => s + v.bugs, 0);
  const totalRemaining = summaryRows.reduce((s, [, v]) => s + v.remaining, 0);
  const totalCompleted = summaryRows.reduce((s, [, v]) => s + v.completed, 0);

  return (
    <div>
      <h2 className="page-title">
        Work Items — <span className="period">{period}</span>
        {team && <span className="team-badge">{team}</span>}
        <button className="sync-btn" onClick={handleSync} disabled={syncing || !period}>
          {syncing ? "Syncing…" : "⟳ Sync"}
        </button>
        {syncMsg && <span className="sync-msg">{syncMsg}</span>}
      </h2>

      <div className="filter-section">
        <ChipGroup label="Engineer" options={engineers} selected={selEngs}
          onToggle={v => setSelEngs(toggle(selEngs, v))} counts={engCounts} />
        <ChipGroup label="Type" options={types} selected={selTypes}
          onToggle={v => setSelTypes(toggle(selTypes, v))} counts={typeCounts} />
        <ChipGroup label="State" options={states} selected={selStates}
          onToggle={v => setSelStates(toggle(selStates, v))} counts={stateCounts} />
        <ChipGroup label="Spillover" options={spilledOptions} selected={selSpilled}
          onToggle={v => setSelSpilled(toggle(selSpilled, v))} counts={spilledCounts} />
        <ChipGroup label="Sprint span" options={sprintSpanOptions} selected={selSprints}
          onToggle={v => setSelSprints(toggle(selSprints, v))} counts={sprintSpanCounts} />
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

      <table className="data-table summary-table">
        <thead>
          <tr>
            {filteredCapacity != null && <th className="num">Capacity (h)</th>}
            <th className="num">Remaining (h)</th>
            <th className="num">Completed (h)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            {filteredCapacity != null && <td className="num">{filteredCapacity.toFixed(1)}</td>}
            <td className="num">{totalRemaining.toFixed(1)}</td>
            <td className="num">{totalCompleted.toFixed(1)}</td>
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
