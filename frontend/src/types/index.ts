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
  category: string | null;
  subcategory: string | null;
  priority_score: number | null;
  risk_level: string | null;
  address: string | null;
  ward: string | null;
  district: string | null;
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
  resolution_rate: number;
  by_category: Record<string, number>;
  by_status: Record<string, number>;
  heatmap_data: Array<{ lat: number; lng: number; category: string; status: string; risk_level: string | null; color: string }>;
  recent_complaints: Array<{
    id: string;
    description: string;
    category: string;
    status: string;
    address: string;
    created_at: string;
    risk_level: string;
    media_url: string | null;
    citizen_name: string | null;
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
