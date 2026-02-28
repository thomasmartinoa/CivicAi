import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { useEffect } from 'react';
import { getAnalytics, getPerformanceMetrics, getLatestBriefing } from '../../services/api';
import api from '../../services/api';
import type { Analytics, PerformanceMetrics } from '../../types';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import type { PieLabelRenderProps } from 'recharts';

const PIE_COLORS = ['#16a34a', '#eab308', '#f97316', '#ef4444', '#6b7280'];

export default function AdminDashboard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!localStorage.getItem('admin_token')) {
      navigate('/admin/login');
    }
  }, [navigate]);

  const handleLogout = () => {
    localStorage.removeItem('admin_token');
    queryClient.clear();
    navigate('/admin/login');
  };

  const { data, isLoading, isError } = useQuery<Analytics>({
    queryKey: ['adminAnalytics'],
    queryFn: async () => {
      const res = await getAnalytics();
      return res.data;
    },
    retry: false,
    staleTime: 0,
    refetchInterval: 15000,
  });

  const { data: perf } = useQuery<PerformanceMetrics>({
    queryKey: ['adminPerformance'],
    queryFn: async () => {
      const res = await getPerformanceMetrics();
      return res.data;
    },
    retry: false,
    staleTime: 0,
    refetchInterval: 15000,
  });

  const { data: briefingData, refetch: refetchBriefing } = useQuery({
    queryKey: ['adminBriefing'],
    queryFn: async () => {
      const res = await getLatestBriefing();
      return res.data;
    },
    retry: false,
  });

  const generateBriefingMutation = useMutation({
    mutationFn: () => api.post('/admin/briefing/generate'),
    onSuccess: () => refetchBriefing(),
  });

  const clusterMutation = useMutation({
    mutationFn: () => api.post('/admin/cluster/detect'),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900"></div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="text-center py-20">
        <p className="text-red-600 mb-4">Failed to load analytics. Are you logged in?</p>
        <Link to="/admin/login" className="text-blue-600 underline">Go to Login</Link>
      </div>
    );
  }

  const openCount = Object.entries(data.by_status || {})
    .filter(([s]) => !['resolved', 'closed'].includes(s))
    .reduce((sum, [, v]) => sum + (v as number), 0);
  const resolvedCount = (data.by_status?.['resolved'] || 0) + (data.by_status?.['closed'] || 0);
  const criticalCount = data.by_risk_level?.['critical'] || 0;

  const categoryData = Object.entries(data.by_category || {}).map(([name, value]) => ({ name, value }));
  const riskData = Object.entries(data.by_risk_level || {}).map(([name, value]) => ({ name, value }));

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Admin Dashboard</h1>
        <div className="flex gap-2">
          <Link to="/admin/complaints" className="px-4 py-2 bg-blue-900 text-white rounded-lg hover:bg-blue-800 transition text-sm">
            View All Complaints
          </Link>
          <button onClick={handleLogout} className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition text-sm">
            Logout
          </button>
        </div>
      </div>

      {/* AI Action Bar */}
      <div className="mb-6 flex flex-wrap gap-3 p-4 bg-blue-50 rounded-xl border border-blue-200">
        <span className="text-sm font-semibold text-blue-900 self-center mr-2">🤖 AI Actions:</span>
        <button
          onClick={() => generateBriefingMutation.mutate()}
          disabled={generateBriefingMutation.isPending}
          className="px-4 py-2 bg-blue-900 text-white text-sm rounded-lg hover:bg-blue-800 transition disabled:opacity-50"
        >
          {generateBriefingMutation.isPending ? 'Generating...' : 'Generate Officer Briefing'}
        </button>
        <button
          onClick={() => clusterMutation.mutate()}
          disabled={clusterMutation.isPending}
          className="px-4 py-2 bg-purple-700 text-white text-sm rounded-lg hover:bg-purple-800 transition disabled:opacity-50"
        >
          {clusterMutation.isPending ? 'Detecting...' : 'Run Cluster Detection'}
        </button>
        {clusterMutation.isSuccess && (
          <span className="text-sm text-green-700 self-center">{(clusterMutation.data as any)?.data?.message}</span>
        )}
      </div>

      {/* AI Officer Briefing Panel */}
      {briefingData?.briefing && (
        <div className="mb-6 bg-white rounded-xl border border-blue-200 shadow-sm p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-base font-semibold text-blue-900">📋 Officer Daily Briefing</h2>
            <span className="text-xs text-gray-400">
              {new Date(briefingData.briefing.brief_date).toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })}
            </span>
          </div>
          <div className="grid grid-cols-4 gap-3 mb-4">
            {[
              { label: 'New today', value: briefingData.briefing.new_complaints, color: 'text-blue-900' },
              { label: 'Resolved', value: briefingData.briefing.resolved_today, color: 'text-green-600' },
              { label: 'SLA at risk', value: briefingData.briefing.sla_at_risk, color: 'text-red-600' },
              { label: 'Escalations', value: briefingData.briefing.escalations_today, color: 'text-orange-600' },
            ].map(item => (
              <div key={item.label} className="bg-gray-50 rounded-lg p-3 text-center">
                <div className={`text-2xl font-bold ${item.color}`}>{item.value}</div>
                <div className="text-xs text-gray-500 mt-0.5">{item.label}</div>
              </div>
            ))}
          </div>
          <p className="text-sm text-gray-700 leading-relaxed bg-gray-50 rounded-lg p-4 italic">
            "{briefingData.briefing.narrative}"
          </p>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <p className="text-sm text-gray-500 mb-1">Total</p>
          <p className="text-3xl font-bold text-blue-900">{data.total_complaints}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <p className="text-sm text-gray-500 mb-1">Open</p>
          <p className="text-3xl font-bold text-yellow-600">{openCount}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <p className="text-sm text-gray-500 mb-1">Resolved</p>
          <p className="text-3xl font-bold text-green-600">{resolvedCount}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <p className="text-sm text-gray-500 mb-1">Critical</p>
          <p className="text-3xl font-bold text-red-600">{criticalCount}</p>
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">Complaints by Category</h2>
          {categoryData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={categoryData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" angle={-30} textAnchor="end" height={80} fontSize={12} />
                <YAxis />
                <Tooltip />
                <Bar dataKey="value" fill="#1e3a5f" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-400 text-center py-12">No data available</p>
          )}
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">Risk Level Distribution</h2>
          {riskData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={riskData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={(props: PieLabelRenderProps) => `${props.name ?? ''} (${(((props.percent as number) ?? 0) * 100).toFixed(0)}%)`}
                  outerRadius={100}
                  dataKey="value"
                >
                  {riskData.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-400 text-center py-12">No data available</p>
          )}
        </div>
      </div>

      {/* Performance Metrics */}
      {perf && (
        <div className="mt-6 space-y-4">
          <h2 className="text-xl font-bold text-gray-800">Performance Metrics</h2>

          {/* SLA & Escalations KPIs */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <p className="text-sm text-gray-500 mb-1">SLA Breach Rate</p>
              <p className={`text-3xl font-bold ${perf.sla_breach_rate_percent > 20 ? 'text-red-600' : 'text-green-600'}`}>
                {perf.sla_breach_rate_percent}%
              </p>
              <p className="text-xs text-gray-400 mt-1">{perf.sla_breaches} of {perf.sla_total_measured} orders</p>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <p className="text-sm text-gray-500 mb-1">Total Escalations</p>
              <p className="text-3xl font-bold text-orange-600">{perf.total_escalations}</p>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <p className="text-sm text-gray-500 mb-1">Contractors Active</p>
              <p className="text-3xl font-bold text-blue-900">{perf.contractor_performance.length}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Avg Resolution Time by Category */}
            {Object.keys(perf.avg_resolution_hours_by_category).length > 0 && (
              <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                <h3 className="text-base font-semibold text-gray-800 mb-4">Avg Resolution Time (hours) by Category</h3>
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={Object.entries(perf.avg_resolution_hours_by_category).map(([name, value]) => ({ name, value }))}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" angle={-30} textAnchor="end" height={80} fontSize={11} />
                    <YAxis />
                    <Tooltip formatter={(v) => [`${v}h`, 'Avg Hours']} />
                    <Bar dataKey="value" fill="#16a34a" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Contractor Performance Table */}
            {perf.contractor_performance.length > 0 && (
              <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                <h3 className="text-base font-semibold text-gray-800 mb-4">Contractor Performance</h3>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 text-left text-gray-500">
                      <th className="pb-2 font-medium">Contractor</th>
                      <th className="pb-2 font-medium">Completed</th>
                      <th className="pb-2 font-medium">Avg Hours</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perf.contractor_performance.map((c) => (
                      <tr key={c.contractor_id} className="border-b border-gray-100 hover:bg-gray-50">
                        <td className="py-2 text-gray-800">{c.name}</td>
                        <td className="py-2 text-gray-600">{c.completed_orders}</td>
                        <td className="py-2 text-gray-600">{c.avg_resolution_hours}h</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
