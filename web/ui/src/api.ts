export async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, window.location.origin);
  if (params) Object.entries(params).forEach(([k, v]) => v && url.searchParams.set(k, v));
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export async function post<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, window.location.origin);
  if (params) Object.entries(params).forEach(([k, v]) => v && url.searchParams.set(k, v));
  const res = await fetch(url.toString(), { method: "POST" });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export interface Sprint {
  name: string;
  start_date: string;
  end_date: string;
  time_frame: string;
  team_name: string;
}

export interface Team {
  id: string;
  name: string;
  description: string;
}

export interface SummaryRow {
  engineer: string;
  commits: number;
  prs: number;
  avg_review_hours: number | null;
}

export interface Commit {
  commit_date: string;
  repo: string;
  branch: string;
  message: string;
  url: string;
}

export interface PR {
  pr_id: number;
  repo: string;
  title: string;
  status: string;
  source_branch: string;
  target_branch: string;
  created_date: string;
  closed_date: string | null;
  review_time_hours: number | null;
  url: string;
}

export interface LinkedPR {
  pr_id: number;
  repo: string;
  url: string;
}

export interface WorkItem {
  id: number;
  engineer_email: string;
  type: string;
  state: string;
  title: string;
  story_points: number | null;
  effort: number | null;
  remaining_work: number | null;
  original_estimate: number | null;
  completed_work: number | null;
  area_path: string;
  iteration_path: string;
  changed_date: string;
  url: string;
  linked_prs: LinkedPR[];
}
