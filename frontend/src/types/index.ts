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

export interface WorkOrder {
  id: string;
  complaint_id: string;
  contractor_id: string | null;
  status: string;
  sla_deadline: string | null;
  estimated_cost: number | null;
  notes: string | null;
  created_at: string;
  completion_photo: string | null;
}

export interface Contractor {
  id: string;
  name: string;
  specializations: string[];
  rating: number;
  active_workload: number;
  zone: string;
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
}

export interface PerformanceMetrics {
  avg_resolution_hours_by_category: Record<string, number>;
  sla_breach_rate_percent: number;
  sla_breaches: number;
  sla_total_measured: number;
  contractor_performance: Array<{
    contractor_id: string;
    name: string;
    completed_orders: number;
    avg_resolution_hours: number;
  }>;
  total_escalations: number;
}
