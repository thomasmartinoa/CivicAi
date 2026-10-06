/** Both officer list endpoints return a page, not a bare array: `items` plus the
 *  counts. The field is called `items` on purpose — it is the same shape for
 *  complaints and work orders, so a screen can share the handling. */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface ComplaintMedia {
  file_path: string;
  media_type: string;
  original_filename: string | null;
}

export interface Complaint {
  id: string;
  tracking_id: string;
  status: string;
  description: string;
  citizen_email: string;
  citizen_name: string | null;
  category: string | null;
  subcategory: string | null;
  priority_score: number | null;
  risk_level: string | null;
  address: string | null;
  ward: string | null;
  district: string | null;
  state: string | null;
  latitude: number | null;
  longitude: number | null;
  created_at: string;
  updated_at: string;
  media: ComplaintMedia[];
  satisfaction_rating: number | null;
  verified_fixed: boolean | null;
  reopen_count: number;
}

/** A row in the officer queue. Not a whole Complaint: the list endpoint sends a
 *  summary, and `description_preview` is truncated server-side. */
export interface ComplaintRow {
  id: string;
  tracking_id: string;
  status: string;
  category: string | null;
  risk_level: string | null;
  priority_score: number | null;
  district: string | null;
  ward: string | null;
  classification_confidence: number | null;
  created_at: string;
  /** on_track | warning | urgent | breached — computed from the work order's own
   *  window, so it is absent when there is no work order yet. */
  sla_state: string | null;
  is_cluster: boolean;
  description_preview: string | null;
}

export interface WorkOrder {
  id: string;
  complaint_id: string;
  /** The tracking id of the complaint, so a row is identifiable without a second
   *  request. */
  tracking_id: string;
  category: string | null;
  risk_level: string | null;
  status: string;
  sla_hours: number | null;
  sla_deadline: string | null;
  /** Computed by the server from the order's own window. */
  sla_state: string;
  /** The name, not the id: the list endpoint resolves it so the screen does not
   *  have to hold a contractor lookup. */
  contractor_name: string | null;
  estimated_cost: number | null;
  is_cluster: boolean;
  cluster_size: number | null;
  created_at: string;
  completed_at: string | null;
  /** Always null today: nothing uploads one yet. The screen must not make
   *  completion depend on it, or no order could ever be completed. */
  completion_photo: string | null;
}

/** As /admin/contractors sends it. `contractor_id`, not `id`, and every performance
 *  figure may be null: a crew that has completed nothing has no median resolution
 *  time, and 0 hours would read as instant work. */
export interface Contractor {
  contractor_id: string;
  name: string;
  specializations: string[];
  rating: number | null;
  active_workload: number;
  completed: number;
  median_hours: number | null;
  breached: number;
}

export interface DashboardStats {
  total_complaints: number;
  resolved_complaints: number;
  /** null when nothing has been filed. The API deliberately does not send 0, because
   *  0% reads as a municipality that resolves nothing rather than one with nothing to
   *  resolve, so this must render as "No data" and never as a number. */
  resolution_rate: number | null;
  by_category: Record<string, number>;
  by_status: Record<string, number>;
  /** A coarsened grid cell, not a complaint. The coordinates are rounded to about
   *  110 m before grouping, and `weight` is how many complaints fell in the cell —
   *  the public API never exposes a single complaint's exact position. */
  heatmap_data: Array<{ lat: number; lng: number; weight: number; category: string | null }>;
  /** What a stranger may see. `description`, `address` and `citizen_name` are NOT
   *  here: the public endpoint withholds them on purpose, because a complaint
   *  description is unreviewed free text about a real street and a place plus a date
   *  is often a household. `media_url` is always null until a moderation step exists.
   *  See backend/app/schemas/public.py for the full list of exclusions. */
  recent_complaints: Array<{
    id: string;
    category: string | null;
    status: string;
    risk_level: string | null;
    district: string | null;
    state: string | null;
    created_at: string;
    resolved: boolean;
    media_url: string | null;
  }>;
}

export interface Analytics {
  total_complaints: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_risk_level: Record<string, number>;
  completed_work_orders: number;
  /** All four are null rather than 0 when nothing has completed, because 0 hours
   *  reads as instant resolution. Render "No data". */
  median_resolution_hours: number | null;
  mean_resolution_hours: number | null;
  fastest_resolution_hours: number | null;
  slowest_resolution_hours: number | null;
  sla_measured: number;
  sla_met: number;
  sla_breached: number;
  /** null with nothing completed — not 1.0, which would read as a perfect record
   *  rather than an empty one. */
  sla_compliance_rate: number | null;
}

/** /admin/analytics/performance and /admin/contractors return the same shape. The
 *  v1-era type here also carried avg_resolution_hours_by_category and
 *  total_escalations; neither endpoint provides them, and they are listed as
 *  deferred in Phase 4a's carried-forward section rather than faked. */
export interface PerformanceMetrics {
  contractors: Contractor[];
}

/** One step in an agent run's timeline. */
export interface AgentStep {
  seq: number;
  node: string;
  /** `completed`, `failed`, or `step_limit` — the last meaning the agent ran out of
   *  steps. Rendered as `completed` it would be indistinguishable from finishing. */
  status: string;
  duration_ms: number | null;
  tokens: number | null;
  input_summary: string | null;
  output_summary: string | null;
  error: string | null;
  created_at: string;
}

export interface AgentRun {
  id: string;
  complaint_id: string | null;
  /** null for a chat run, which belongs to no single complaint. */
  tracking_id: string | null;
  /** `pipeline` or `chat`, derived server-side so the screen does not have to know
   *  that a null complaint_id means a conversation. */
  kind: string;
  thread_id: string;
  status: string;
  graph_version: string | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  error: string | null;
  step_count: number;
  /** What the run was about: a tracking id for a pipeline run, the opening question
   *  for a conversation. Without it the list is a column of identical rows. */
  label: string | null;
}

export interface AgentRunDetail extends AgentRun {
  steps: AgentStep[];
}


/** One citation behind a pipeline decision, as /admin/complaints/{id} sends it. */
export interface EvidenceCitation {
  /** Which node retrieved it: validate, classify, assess_risk, route, work_order. */
  node: string;
  source: string;
  /** `source › headers`, the form the graph records and the assistant quotes. */
  citation: string | null;
  snippet: string | null;
  score: number | null;
}
