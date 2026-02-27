import { useQuery } from '@tanstack/react-query';
import { getPublicDashboard } from '../../services/api';
import type { DashboardStats } from '../../types';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import type { PieLabelRenderProps } from 'recharts';

const PIE_COLORS = ['#1e3a5f', '#2563eb', '#16a34a', '#eab308', '#ef4444', '#8b5cf6', '#6b7280'];

export default function PublicDashboard() {
  const { data, isLoading, isError } = useQuery<DashboardStats>({
    queryKey: ['publicDashboard'],
    queryFn: async () => {
      const res = await getPublicDashboard();
      return res.data;
    },
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
        <p className="text-red-600">Failed to load dashboard data.</p>
      </div>
    );
  }

  const categoryData = Object.entries(data.by_category || {}).map(([name, value]) => ({ name, value }));
  const statusData = Object.entries(data.by_status || {}).map(([name, value]) => ({ name, value }));

  return (
    <div>
      <h1 className="text-3xl font-bold text-gray-900 mb-6">Public Dashboard</h1>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <p className="text-sm text-gray-500 mb-1">Total Complaints</p>
          <p className="text-4xl font-bold text-blue-900">{data.total_complaints}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <p className="text-sm text-gray-500 mb-1">Resolved</p>
          <p className="text-4xl font-bold text-green-600">{data.resolved_complaints}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <p className="text-sm text-gray-500 mb-1">Resolution Rate</p>
          <p className="text-4xl font-bold text-purple-600">
            {(data.resolution_rate * 100).toFixed(1)}%
          </p>
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Category Bar Chart */}
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

        {/* Status Pie Chart */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">Status Distribution</h2>
          {statusData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={statusData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={(props: PieLabelRenderProps) => `${props.name ?? ''} (${(((props.percent as number) ?? 0) * 100).toFixed(0)}%)`}
                  outerRadius={100}
                  dataKey="value"
                >
                  {statusData.map((_, i) => (
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
    </div>
  );
}
