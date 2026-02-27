import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { getWorkOrders, updateWorkOrder } from '../../services/api';
import type { WorkOrder } from '../../types';

const statusColor: Record<string, string> = {
  created: 'bg-gray-100 text-gray-700',
  assigned: 'bg-blue-100 text-blue-800',
  in_progress: 'bg-yellow-100 text-yellow-800',
  completed: 'bg-green-100 text-green-800',
  cancelled: 'bg-red-100 text-red-700',
};

const STATUS_OPTIONS = ['created', 'assigned', 'in_progress', 'completed', 'cancelled'];

export default function AdminWorkOrders() {
  const navigate = useNavigate();
  const [filterStatus, setFilterStatus] = useState('');
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!localStorage.getItem('admin_token')) navigate('/admin/login');
  }, [navigate]);

  const { data, isLoading, isError } = useQuery<WorkOrder[]>({
    queryKey: ['adminWorkOrders', filterStatus],
    queryFn: async () => {
      const res = await getWorkOrders(filterStatus || undefined);
      return res.data.work_orders;
    },
  });

  const mutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      updateWorkOrder(id, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminWorkOrders'] });
    },
  });

  if (isError) {
    return (
      <div className="text-center py-20">
        <p className="text-red-600 mb-4">Failed to load work orders. Are you logged in?</p>
        <Link to="/admin/login" className="text-blue-600 underline">Go to Login</Link>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Work Orders</h1>
        <Link to="/admin" className="text-blue-600 hover:underline text-sm">Back to Dashboard</Link>
      </div>

      {/* Filter */}
      <div className="mb-6">
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white"
        >
          <option value="">All Statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
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
                <th className="text-left px-4 py-3 font-medium text-gray-600">Complaint ID</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Contractor</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">SLA Deadline</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Est. Cost</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(data || []).length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center text-gray-400 py-12">No work orders found</td>
                </tr>
              ) : (
                (data || []).map((wo) => (
                  <tr key={wo.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs">{wo.complaint_id.slice(0, 8)}...</td>
                    <td className="px-4 py-3">{wo.contractor_id ? wo.contractor_id.slice(0, 8) + '...' : 'Unassigned'}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${statusColor[wo.status] || 'bg-gray-100'}`}>
                        {wo.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {wo.sla_deadline ? new Date(wo.sla_deadline).toLocaleDateString() : '-'}
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      {wo.estimated_cost != null ? `$${wo.estimated_cost.toLocaleString()}` : '-'}
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={wo.status}
                        onChange={(e) => mutation.mutate({ id: wo.id, status: e.target.value })}
                        disabled={mutation.isPending}
                        className="border border-gray-300 rounded px-2 py-1 text-xs bg-white"
                      >
                        {STATUS_OPTIONS.map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {mutation.isError && (
        <div className="mt-4 bg-red-50 border border-red-300 text-red-700 rounded-lg p-3 text-sm">
          Failed to update work order status.
        </div>
      )}
    </div>
  );
}
