import type { EvidenceCitation } from '../../types';
import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getAdminComplaintDetail, approveComplaintEmail, API_BASE_URL } from '../../services/api';

const statusColor: Record<string, string> = {
  submitted: 'bg-gray-100 text-gray-700',
  processing: 'bg-yellow-100 text-yellow-800',
  categorized: 'bg-blue-100 text-blue-800',
  assigned: 'bg-purple-100 text-purple-800',
  in_progress: 'bg-orange-100 text-orange-800',
  resolved: 'bg-green-100 text-green-800',
  closed: 'bg-gray-200 text-gray-600',
};

const riskBadge: Record<string, string> = {
  low: 'bg-green-100 text-green-800',
  medium: 'bg-yellow-100 text-yellow-800',
  high: 'bg-orange-100 text-orange-800',
  critical: 'bg-red-100 text-red-800',
};

export default function AdminComplaintDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [emailDraft, setEmailDraft] = useState('');
  const [emailStatus, setEmailStatus] = useState<'draft' | 'approved'>('draft');

  useEffect(() => {
    if (!localStorage.getItem('admin_token')) navigate('/admin/login');
  }, [navigate]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['adminComplaintDetail', id],
    queryFn: async () => {
      const res = await getAdminComplaintDetail(id!);
      return res.data;
    },
    enabled: !!id,
  });

  useEffect(() => {
    if (data) {
      setEmailDraft(data.email_draft || '');
      setEmailStatus(data.email_approved ? 'approved' : 'draft');
    }
  }, [data]);

  const approveMutation = useMutation({
    mutationFn: () => approveComplaintEmail(id!, emailDraft),
    onSuccess: () => {
      setEmailStatus('approved');
      queryClient.invalidateQueries({ queryKey: ['adminComplaintDetail', id] });
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
        <p className="text-red-600 mb-4">Failed to load complaint details.</p>
        <Link to="/admin/complaints" className="text-blue-600 underline">Back to Complaints</Link>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/admin/complaints')}
            className="text-blue-600 hover:text-blue-800 text-sm flex items-center gap-1"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
            </svg>
            Back to Complaints
          </button>
        </div>
      </div>

      {/* Title Bar */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
        <div className="flex flex-wrap items-center gap-3 mb-2">
          <h1 className="text-2xl font-bold text-gray-900">Complaint Report</h1>
          <span className="font-mono text-sm bg-gray-100 text-gray-600 px-3 py-1 rounded-lg">{data.tracking_id}</span>
          <span className={`px-3 py-1 rounded-full text-xs font-semibold ${statusColor[data.status] || 'bg-gray-100'}`}>
            {data.status}
          </span>
          {data.risk_level && (
            <span className={`px-3 py-1 rounded-full text-xs font-semibold ${riskBadge[data.risk_level] || 'bg-gray-100'}`}>
              {data.risk_level.toUpperCase()} RISK
            </span>
          )}
        </div>
        <p className="text-sm text-gray-500">
          Filed on {new Date(data.created_at).toLocaleString()} | Category: <span className="font-medium text-gray-700">{data.category || 'Uncategorized'}</span>
          {data.subcategory && <> / {data.subcategory}</>}
          {data.priority_score != null && <> | Priority: <span className="font-medium">{data.priority_score}/100</span></>}
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Complaint Details */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">Complaint Details</h2>
          <div className="space-y-4">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase mb-1">Description</p>
              <p className="text-gray-800 leading-relaxed">{data.description}</p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-1">Citizen Name</p>
                <p className="text-gray-800">{data.citizen_name || 'Anonymous'}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-1">Email</p>
                <p className="text-gray-800">{data.citizen_email}</p>
              </div>
              {data.citizen_phone && (
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase mb-1">Phone</p>
                  <p className="text-gray-800">{data.citizen_phone}</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Location */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">Location</h2>
          <div className="space-y-3">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase mb-1">Address</p>
              <p className="text-gray-800">{data.address || 'Not specified'}</p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              {data.ward && (
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase mb-1">Ward</p>
                  <p className="text-gray-800">{data.ward}</p>
                </div>
              )}
              {data.district && (
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase mb-1">District</p>
                  <p className="text-gray-800">{data.district}</p>
                </div>
              )}
              {data.state && (
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase mb-1">State</p>
                  <p className="text-gray-800">{data.state}</p>
                </div>
              )}
              {data.latitude && data.longitude && (
                <div>
                  <p className="text-xs font-medium text-gray-500 uppercase mb-1">GPS</p>
                  <p className="text-gray-800 text-sm">{data.latitude.toFixed(5)}, {data.longitude.toFixed(5)}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* What the pipeline decided, and what it cited.

          Replaces a block that read a nested `ai_analysis` object the v2 API has
          never sent — classification, risk and routing live on the complaint itself,
          and the citations behind them live in `evidence`. The old block rendered
          nothing at all, which is why four phases of grounding work have been
          invisible. */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-gray-800 mb-4">What the pipeline decided</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-blue-50 rounded-lg p-4">
            <p className="text-xs font-medium text-blue-600 uppercase mb-2">Classification</p>
            <p className="text-sm text-gray-800">
              {data.category ?? 'not classified'}
              {data.subcategory ? ` / ${data.subcategory}` : ''}
            </p>
            <p className="text-xs text-gray-500 mt-1">
              {/* Null means the model never ran, which is not the same as 0%
                  confidence — one is an absent judgement, the other a bad one. */}
              {data.classification_confidence == null
                ? 'Confidence not recorded'
                : `Confidence ${(data.classification_confidence * 100).toFixed(0)}%`}
            </p>
          </div>

          <div className="bg-orange-50 rounded-lg p-4">
            <p className="text-xs font-medium text-orange-600 uppercase mb-2">Risk</p>
            <p className="text-sm text-gray-800 capitalize">{data.risk_level ?? 'not assessed'}</p>
            <p className="text-xs text-gray-500 mt-1">
              {data.priority_score == null ? 'No score' : `Priority ${data.priority_score}/100`}
            </p>
          </div>

          <div className="bg-purple-50 rounded-lg p-4">
            <p className="text-xs font-medium text-purple-600 uppercase mb-2">Routing</p>
            <p className="text-sm text-gray-800">
              {data.work_order?.contractor_name ?? 'No contractor assigned'}
            </p>
            {data.work_order?.sla_hours != null && (
              <p className="text-xs text-gray-500 mt-1">
                {data.work_order.sla_hours}h SLA · {data.work_order.sla_state}
              </p>
            )}
          </div>
        </div>

        {/* The justification route wrote, with its [n] markers pointing into the
            citations below. This sentence is what an officer is accountable for. */}
        {data.routing_justification && (
          <div className="mt-4 bg-gray-50 border border-gray-200 rounded-lg p-4">
            <p className="text-xs font-medium text-gray-500 uppercase mb-2">Justification</p>
            <p className="text-sm text-gray-800">{data.routing_justification}</p>
          </div>
        )}

        {data.terminal_reason && (
          <div className="mt-4 bg-amber-50 border border-amber-300 rounded-lg p-4">
            <p className="text-xs font-medium text-amber-800 uppercase mb-1">
              Rejected — not a failure
            </p>
            <p className="text-sm text-gray-800">{data.terminal_reason}</p>
          </div>
        )}
      </div>

      {/* Evidence */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-gray-800">Evidence</h2>
        <p className="text-sm text-gray-500 mt-1 mb-4">
          The municipal documents each decision was grounded in. A decision with no
          citation was made without one.
        </p>

        {(!data.evidence || data.evidence.length === 0) ? (
          /* Said plainly rather than hidden. Retrieval is a soft dependency — a
             complaint processed while the index was unavailable is routed on the
             model's own judgement, and an officer should be able to see that. */
          <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
            No citations recorded. This complaint was processed without retrieval, so
            its decisions are ungrounded.
          </p>
        ) : (
          <div className="space-y-3">
            {data.evidence.map((item: EvidenceCitation, index: number) => (
              <div key={index} className="border border-gray-200 rounded-lg p-4">
                <div className="flex items-center gap-2 flex-wrap mb-2">
                  <span className="text-xs font-semibold px-2 py-1 rounded bg-gray-100 text-gray-700">
                    {item.node}
                  </span>
                  <span className="text-xs font-mono text-gray-600 break-all">
                    {item.citation || item.source}
                  </span>
                  {item.score != null && (
                    <span className="text-xs text-gray-400 ml-auto">
                      relevance {item.score.toFixed(3)}
                    </span>
                  )}
                </div>
                {item.snippet && (
                  <p className="text-sm text-gray-700 whitespace-pre-wrap">{item.snippet}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Attachments */}
      {data.media && data.media.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">Attachments ({data.media.length})</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {data.media.map((m: any) => (
              <div key={m.id} className="border border-gray-200 rounded-lg overflow-hidden">
                {m.media_type === 'image' ? (
                  <img
                    src={`${API_BASE_URL}/${m.file_path}`}
                    alt={m.original_filename || 'Attachment'}
                    className="w-full h-32 object-cover"
                  />
                ) : (
                  <div className="w-full h-32 bg-gray-50 flex items-center justify-center text-gray-400">
                    <div className="text-center">
                      <svg className="w-8 h-8 mx-auto mb-1 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                      </svg>
                      <span className="text-xs">{m.media_type}</span>
                    </div>
                  </div>
                )}
                <div className="p-2 text-xs text-gray-500 truncate">{m.original_filename || 'File'}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Work Order */}
      {data.work_order && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">Work Order</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase mb-1">Status</p>
              <p className="text-gray-800 font-medium">{data.work_order.status}</p>
            </div>
            {data.work_order.sla_deadline && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-1">SLA Deadline</p>
                <p className="text-gray-800">{new Date(data.work_order.sla_deadline).toLocaleString()}</p>
              </div>
            )}
            {data.work_order.estimated_cost != null && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-1">Estimated Cost</p>
                <p className="text-gray-800 font-medium">Rs. {data.work_order.estimated_cost.toLocaleString()}</p>
              </div>
            )}
            {data.work_order.notes && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase mb-1">Notes</p>
                <p className="text-gray-800 text-sm">{data.work_order.notes}</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Email Draft Section */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-800">Email draft to the department</h2>
          <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
            emailStatus === 'approved' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'
          }`}>
            {emailStatus === 'approved' ? 'Approved' : 'Draft'}
          </span>
        </div>

        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <textarea
            value={emailDraft}
            onChange={(e) => {
              setEmailDraft(e.target.value);
              if (emailStatus === 'approved') setEmailStatus('draft');
            }}
            rows={16}
            className="w-full p-4 text-sm text-gray-800 font-mono leading-relaxed resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 border-0"
            placeholder="Email draft will be generated..."
          />
        </div>

        <div className="flex items-center justify-between mt-4">
          <p className="text-xs text-gray-400">
            {emailStatus === 'approved'
              ? 'This email has been approved. Editing will reset to draft status.'
              : 'Review and edit the email draft, then approve to finalize.'}
          </p>
          <button
            onClick={() => approveMutation.mutate()}
            disabled={approveMutation.isPending || emailStatus === 'approved'}
            className={`px-6 py-2.5 rounded-lg text-sm font-medium transition ${
              emailStatus === 'approved'
                ? 'bg-green-100 text-green-700 cursor-not-allowed'
                : 'bg-[#3B5BDB] text-white hover:bg-[#364FC7]'
            }`}
          >
            {approveMutation.isPending ? 'Approving...' : emailStatus === 'approved' ? 'Approved' : 'Approve Email'}
          </button>
        </div>
        {approveMutation.isError && (
          <p className="text-red-600 text-sm mt-2">Failed to approve email. Please try again.</p>
        )}
      </div>
    </div>
  );
}
