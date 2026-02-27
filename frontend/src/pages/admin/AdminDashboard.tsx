import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getAnalytics } from '../../services/api';
import type { Analytics } from '../../types';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import type { PieLabelRenderProps } from 'recharts';

const PIE_COLORS = ['#16a34a', '#eab308', '#f97316', '#ef4444', '#6b7280'];

export default function AdminDashboard() {
  const { data, isLoading, isError } = useQuery<Analytics>({
    queryKey: ['adminAnalytics'],
    queryFn: async () => {
      const res = await getAnalytics();
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
        <p className="text-red-600 mb-4">Failed to load analytics. Are you logged in?</p>
        <Link to="/admin/login" className="text-blue-600 underline">Go to Login</Link>
      </div>
    );
  }

  const openCount = (data.by_status?.['submitted'] || 0) + (data.by_status?.['processing'] || 0) + (data.by_status?.['categorized'] || 0);
  const resolvedCount = data.by_status?.['resolved'] || 0;
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
          <Link to="/admin/work-orders" className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition text-sm">
            View Work Orders
          </Link>
        </div>
      </div>

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
    </div>
  );
}
