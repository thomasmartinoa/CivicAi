import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getAdminComplaints } from '../../services/api';
import type { Complaint } from '../../types';

const statusColor: Record<string, string> = {
  submitted: 'bg-gray-100 text-gray-700',
  processing: 'bg-yellow-100 text-yellow-800',
  categorized: 'bg-blue-100 text-blue-800',
  assigned: 'bg-purple-100 text-purple-800',
  in_progress: 'bg-orange-100 text-orange-800',
  resolved: 'bg-green-100 text-green-800',
  closed: 'bg-gray-200 text-gray-600',
};

const riskColor: Record<string, string> = {
  low: 'text-green-700',
  medium: 'text-yellow-700',
  high: 'text-orange-700',
  critical: 'text-red-700 font-bold',
};

export default function AdminComplaints() {
  const [statusFilter, setStatusFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [riskFilter, setRiskFilter] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const params: Record<string, string> = {};
  if (statusFilter) params.status = statusFilter;
  if (categoryFilter) params.category = categoryFilter;
  if (riskFilter) params.risk_level = riskFilter;

  const { data, isLoading, isError } = useQuery<Complaint[]>({
    queryKey: ['adminComplaints', params],
    queryFn: async () => {
      const res = await getAdminComplaints(params);
      return res.data;
    },
  });

  if (isError) {
    return (
      <div className="text-center py-20">
        <p className="text-red-600 mb-4">Failed to load complaints. Are you logged in?</p>
        <Link to="/admin/login" className="text-blue-600 underline">Go to Login</Link>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold text-gray-900">All Complaints</h1>
        <Link to="/admin" className="text-blue-600 hover:underline text-sm">Back to Dashboard</Link>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white"
        >
          <option value="">All Statuses</option>
          <option value="submitted">Submitted</option>
          <option value="processing">Processing</option>
          <option value="categorized">Categorized</option>
          <option value="assigned">Assigned</option>
          <option value="in_progress">In Progress</option>
          <option value="resolved">Resolved</option>
          <option value="closed">Closed</option>
        </select>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white"
        >
          <option value="">All Categories</option>
          <option value="roads">Roads</option>
          <option value="water">Water</option>
          <option value="sanitation">Sanitation</option>
          <option value="electricity">Electricity</option>
          <option value="parks">Parks</option>
          <option value="noise">Noise</option>
          <option value="other">Other</option>
        </select>
        <select
          value={riskFilter}
          onChange={(e) => setRiskFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white"
        >
          <option value="">All Risk Levels</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-900"></div>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-medium text-gray-600">Tracking ID</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Description</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Category</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Risk</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Date</th>
              </tr>
            </thead>
            <tbody>
              {(data || []).length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center text-gray-400 py-12">No complaints found</td>
                </tr>
              ) : (
                (data || []).map((c) => (
                  <>
                    <tr
                      key={c.id}
                      onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
                      className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition"
                    >
                      <td className="px-4 py-3 font-mono text-xs">{c.tracking_id}</td>
                      <td className="px-4 py-3 max-w-xs truncate">{c.description}</td>
                      <td className="px-4 py-3">{c.category || '-'}</td>
                      <td className={`px-4 py-3 ${riskColor[c.risk_level || ''] || ''}`}>{c.risk_level || '-'}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-1 rounded-full text-xs font-medium ${statusColor[c.status] || 'bg-gray-100'}`}>
                          {c.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-500">{new Date(c.created_at).toLocaleDateString()}</td>
                    </tr>
                    {expandedId === c.id && (
                      <tr key={`${c.id}-detail`} className="bg-blue-50">
                        <td colSpan={6} className="px-6 py-4">
                          <div className="grid grid-cols-2 gap-4 text-sm">
                            <div>
                              <p className="text-gray-500">Full Description</p>
                              <p className="text-gray-800">{c.description}</p>
                            </div>
                            <div className="space-y-2">
                              <p><span className="text-gray-500">Email:</span> {c.citizen_email}</p>
                              <p><span className="text-gray-500">Subcategory:</span> {c.subcategory || '-'}</p>
                              <p><span className="text-gray-500">Priority Score:</span> {c.priority_score ?? '-'}</p>
                              <p><span className="text-gray-500">Address:</span> {c.address || '-'}</p>
                              <p><span className="text-gray-500">Ward:</span> {c.ward || '-'} | <span className="text-gray-500">District:</span> {c.district || '-'}</p>
                              <p><span className="text-gray-500">Updated:</span> {new Date(c.updated_at).toLocaleString()}</p>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
