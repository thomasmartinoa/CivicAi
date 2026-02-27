import { useQuery } from '@tanstack/react-query';
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { getPublicDashboard } from '../../services/api';
import type { DashboardStats } from '../../types';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts';
import type { PieLabelRenderProps } from 'recharts';

const PIE_COLORS = ['#1e3a5f', '#2563eb', '#16a34a', '#eab308', '#ef4444', '#8b5cf6', '#6b7280'];

const RISK_COLOR: Record<string, string> = {
  critical: '#ef4444',
  high: '#f97316',
  medium: '#eab308',
  low: '#16a34a',
};

function getRiskColor(status: string) {
  if (status === 'resolved' || status === 'closed') return '#16a34a';
  return RISK_COLOR['medium'];
}

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
            {data.resolution_rate.toFixed(1)}%
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

      {/* Complaint Heatmap */}
      {data.heatmap_data && data.heatmap_data.length > 0 && (
        <div className="mt-6 bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">
            Complaint Map
            <span className="ml-2 text-sm font-normal text-gray-400">({data.heatmap_data.length} geotagged complaints)</span>
          </h2>
          <div className="rounded-lg overflow-hidden" style={{ height: 400 }}>
            <MapContainer
              center={[data.heatmap_data[0].lat, data.heatmap_data[0].lng]}
              zoom={12}
              style={{ height: '100%', width: '100%' }}
              scrollWheelZoom={false}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              {data.heatmap_data.map((point, i) => (
                <CircleMarker
                  key={i}
                  center={[point.lat, point.lng]}
                  radius={8}
                  pathOptions={{
                    color: getRiskColor(point.status),
                    fillColor: getRiskColor(point.status),
                    fillOpacity: 0.7,
                  }}
                >
                  <Popup>
                    <strong>{point.category}</strong><br />
                    Status: {point.status}
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>
          </div>
          <div className="flex gap-4 mt-3 text-xs text-gray-500">
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-full bg-green-500"></span> Resolved</span>
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-full bg-yellow-400"></span> In Progress</span>
          </div>
        </div>
      )}
    </div>
  );
}
