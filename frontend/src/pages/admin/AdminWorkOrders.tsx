import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { getWorkOrders, updateWorkOrder, uploadCompletionPhoto, API_BASE_URL } from '../../services/api';
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
  const [uploadingId, setUploadingId] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [previewPhoto, setPreviewPhoto] = useState<string | null>(null);
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

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      updateWorkOrder(id, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminWorkOrders'] });
      queryClient.invalidateQueries({ queryKey: ['adminAnalytics'] });
      setUploadError(null);
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail || 'Failed to update status.';
      setUploadError(msg);
    },
  });

  const photoMutation = useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) =>
      uploadCompletionPhoto(id, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminWorkOrders'] });
      queryClient.invalidateQueries({ queryKey: ['adminAnalytics'] });
      setUploadingId(null);
      setUploadError(null);
    },
    onError: () => setUploadError('Photo upload failed.'),
  });

  const handlePhotoSelect = (wo: WorkOrder, file: File) => {
    photoMutation.mutate({ id: wo.id, file });
  };

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

      {/* Info banner */}
      <div className="mb-4 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-sm text-blue-800 flex items-start gap-2">
        <span className="text-lg">📸</span>
        <span>Contractors must upload a <strong>completion photo</strong> before marking a work order as completed. This creates an auditable before/after record.</span>
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

      {/* Preview modal */}
      {previewPhoto && (
        <div
          className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center"
          onClick={() => setPreviewPhoto(null)}
        >
          <div className="relative max-w-2xl w-full mx-4" onClick={e => e.stopPropagation()}>
            <button onClick={() => setPreviewPhoto(null)} className="absolute -top-8 right-0 text-white text-2xl">&times;</button>
            <img src={`${API_BASE_URL}/${previewPhoto}`} alt="Completion proof" className="w-full rounded-xl shadow-2xl" />
            <p className="text-center text-white mt-2 text-sm opacity-75">Completion Proof Photo</p>
          </div>
        </div>
      )}

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
                <th className="text-left px-4 py-3 font-medium text-gray-600">Completion Photo</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(data || []).length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center text-gray-400 py-12">No work orders found</td>
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
                    {/* Completion photo cell */}
                    <td className="px-4 py-3">
                      {wo.completion_photo ? (
                        <button
                          onClick={() => setPreviewPhoto(wo.completion_photo!)}
                          className="relative group"
                          title="Click to enlarge proof photo"
                        >
                          <img
                            src={`${API_BASE_URL}/${wo.completion_photo}`}
                            alt="proof"
                            className="w-12 h-12 object-cover rounded-lg border-2 border-green-400 group-hover:opacity-80 transition"
                          />
                          <span className="absolute -top-1 -right-1 bg-green-500 rounded-full w-4 h-4 flex items-center justify-center text-white text-xs">✓</span>
                        </button>
                      ) : (
                        <div>
                          <label
                            htmlFor={`photo-${wo.id}`}
                            className="cursor-pointer inline-flex items-center gap-1 px-2 py-1 bg-amber-50 border border-amber-300 text-amber-700 rounded-lg text-xs hover:bg-amber-100 transition"
                            title="Upload completion photo before marking complete"
                          >
                            <span>📸</span>
                            {uploadingId === wo.id && photoMutation.isPending ? 'Uploading...' : 'Upload Proof'}
                          </label>
                          <input
                            id={`photo-${wo.id}`}
                            type="file"
                            accept="image/*"
                            className="hidden"
                            onChange={(e) => {
                              const file = e.target.files?.[0];
                              if (file) {
                                setUploadingId(wo.id);
                                handlePhotoSelect(wo, file);
                              }
                              e.target.value = '';
                            }}
                          />
                        </div>
                      )}
                    </td>
                    {/* Status change */}
                    <td className="px-4 py-3">
                      <div className="relative group inline-block">
                        <select
                          value={wo.status}
                          onChange={(e) => statusMutation.mutate({ id: wo.id, status: e.target.value })}
                          disabled={statusMutation.isPending}
                          className="border border-gray-300 rounded px-2 py-1 text-xs bg-white disabled:opacity-60"
                        >
                          {STATUS_OPTIONS.map((s) => (
                            <option key={s} value={s} disabled={s === 'completed' && !wo.completion_photo}>
                              {s === 'completed' && !wo.completion_photo ? '🔒 completed (need photo)' : s}
                            </option>
                          ))}
                        </select>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {uploadError && (
        <div className="mt-4 bg-red-50 border border-red-300 text-red-700 rounded-lg p-3 text-sm">
          {uploadError}
        </div>
      )}
    </div>
  );
}
