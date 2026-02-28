import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { trackComplaint, requestOTP, verifyOTP, getMyComplaints } from '../../services/api';
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
  low: 'bg-green-100 text-green-700',
  medium: 'bg-yellow-100 text-yellow-700',
  high: 'bg-orange-100 text-orange-700',
  critical: 'bg-red-100 text-red-700',
};

function ComplaintCard({ c, expanded, onToggle }: { c: Complaint; expanded: boolean; onToggle: () => void }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="p-5 cursor-pointer hover:bg-gray-50 transition" onClick={onToggle}>
        <div className="flex items-center justify-between mb-3">
          <span className="font-mono text-sm text-gray-500">{c.tracking_id}</span>
          <span className={`px-3 py-1 rounded-full text-xs font-medium ${statusColor[c.status] || 'bg-gray-100 text-gray-700'}`}>
            {c.status}
          </span>
        </div>
        <p className="text-gray-800 mb-3 line-clamp-2">{c.description}</p>
        <div className="flex flex-wrap gap-2 text-xs">
          {c.category && <span className="bg-blue-50 text-blue-700 px-2 py-1 rounded">{c.category}</span>}
          {c.subcategory && <span className="bg-blue-50 text-blue-600 px-2 py-1 rounded">{c.subcategory}</span>}
          {c.risk_level && (
            <span className={`px-2 py-1 rounded ${riskColor[c.risk_level] || ''}`}>Risk: {c.risk_level}</span>
          )}
          {c.priority_score !== null && c.priority_score !== undefined && (
            <span className="bg-gray-100 text-gray-600 px-2 py-1 rounded">Priority: {c.priority_score}</span>
          )}
        </div>
        {c.address && <p className="text-xs text-gray-400 mt-2">{c.address}</p>}
        <div className="flex items-center justify-between mt-2">
          <p className="text-xs text-gray-400">Created: {new Date(c.created_at).toLocaleString()}</p>
          <span className="text-xs text-blue-600">{expanded ? 'Hide details' : 'View details'}</span>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-200 bg-gray-50 p-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Full Description</p>
              <p className="text-gray-800">{c.description}</p>
            </div>
            <div className="space-y-2">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Category</p>
                <p className="text-gray-800">{c.category || '-'} {c.subcategory ? `/ ${c.subcategory}` : ''}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Risk Level</p>
                <p className="text-gray-800 capitalize">{c.risk_level || '-'} {c.priority_score ? `(Score: ${c.priority_score})` : ''}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Location</p>
                <p className="text-gray-800">{c.address || '-'}</p>
                {c.ward && <p className="text-gray-600 text-xs">Ward: {c.ward}</p>}
                {c.district && <p className="text-gray-600 text-xs">District: {c.district}</p>}
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Timeline</p>
                <p className="text-gray-600 text-xs">Created: {new Date(c.created_at).toLocaleString()}</p>
                <p className="text-gray-600 text-xs">Updated: {new Date(c.updated_at).toLocaleString()}</p>
              </div>
            </div>
          </div>

          {/* Media files */}
          {(c as any).media && (c as any).media.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Attachments</p>
              <div className="flex gap-3 flex-wrap">
                {(c as any).media.map((m: any, i: number) => (
                  m.media_type === 'image' ? (
                    <img key={i} src={`http://localhost:8000/${m.file_path}`} alt={m.original_filename || 'attachment'} className="w-24 h-24 object-cover rounded-lg border border-gray-200" />
                  ) : (
                    <div key={i} className="text-xs bg-gray-100 px-3 py-2 rounded">
                      {m.original_filename || m.media_type}
                    </div>
                  )
                ))}
              </div>
            </div>
          )}

          {/* Work order info */}
          {(c as any).work_order && (
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Work Order</p>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <p><span className="text-gray-500">Status:</span> <span className="capitalize">{(c as any).work_order.status}</span></p>
                {(c as any).work_order.sla_deadline && (
                  <p><span className="text-gray-500">SLA Deadline:</span> {new Date((c as any).work_order.sla_deadline).toLocaleString()}</p>
                )}
                {(c as any).work_order.estimated_cost && (
                  <p><span className="text-gray-500">Est. Cost:</span> Rs. {(c as any).work_order.estimated_cost.toLocaleString()}</p>
                )}
                {(c as any).work_order.materials && (
                  <p className="col-span-2"><span className="text-gray-500">Materials:</span> {(c as any).work_order.materials}</p>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function TrackComplaint() {
  const [trackingId, setTrackingId] = useState('');
  const [email, setEmail] = useState('');
  const [otp, setOtp] = useState('');
  const [otpSent, setOtpSent] = useState(false);
  const [verified, setVerified] = useState(false);
  const [myComplaints, setMyComplaints] = useState<Complaint[]>([]);
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const trackMutation = useMutation({
    mutationFn: () => trackComplaint(trackingId),
  });

  const otpMutation = useMutation({
    mutationFn: () => requestOTP(email),
    onSuccess: (res) => {
      setOtpSent(true);
      if (res.data?.dev_otp) {
        setOtp(res.data.dev_otp);
        setDevOtp(res.data.dev_otp);
      }
    },
  });

  const verifyMutation = useMutation({
    mutationFn: () => verifyOTP(email, otp),
    onSuccess: async () => {
      setVerified(true);
      const res = await getMyComplaints(email);
      setMyComplaints(res.data.complaints);
    },
  });

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-10">
      {/* Section 1: Track by ID */}
      <section>
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Track by ID</h1>
        <p className="text-gray-500 mb-4">Enter your tracking ID to check the status of your complaint.</p>
        <div className="flex gap-2">
          <input
            value={trackingId}
            onChange={(e) => setTrackingId(e.target.value)}
            placeholder="e.g. CIV-ABC12345"
            className="flex-1 border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
          />
          <button
            onClick={() => trackMutation.mutate()}
            disabled={!trackingId || trackMutation.isPending}
            className="px-6 py-2 bg-blue-900 text-white rounded-lg hover:bg-blue-800 transition disabled:opacity-50"
          >
            {trackMutation.isPending ? 'Searching...' : 'Search'}
          </button>
        </div>

        {trackMutation.isError && (
          <div className="mt-4 bg-red-50 border border-red-300 text-red-700 rounded-lg p-3 text-sm">
            Complaint not found. Please check the tracking ID.
          </div>
        )}

        {trackMutation.data && (
          <div className="mt-4">
            <ComplaintCard
              c={trackMutation.data.data}
              expanded={expandedId === (trackMutation.data.data as any).id}
              onToggle={() => toggleExpand((trackMutation.data.data as any).id)}
            />
          </div>
        )}
      </section>

      <hr className="border-gray-200" />

      {/* Section 2: View All via Email + OTP */}
      <section>
        <h2 className="text-2xl font-bold text-gray-900 mb-2">View All My Complaints</h2>
        <p className="text-gray-500 mb-4">Verify your email with OTP to see all your submitted complaints.</p>

        {!verified ? (
          <div className="space-y-3">
            <div className="flex gap-2">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
                className="flex-1 border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
              />
              <button
                onClick={() => otpMutation.mutate()}
                disabled={!email || otpMutation.isPending}
                className="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition disabled:opacity-50"
              >
                {otpMutation.isPending ? 'Sending...' : 'Send OTP'}
              </button>
            </div>

            {otpSent && (
              <div className="space-y-2">
                {devOtp && (
                  <div className="flex items-center gap-3 bg-amber-50 border border-amber-300 rounded-lg px-4 py-3 text-sm">
                    <span className="text-amber-600">Dev mode - Email not configured.</span>
                    <span className="text-amber-800 font-medium">Your OTP:</span>
                    <span className="font-mono font-bold text-lg text-amber-900 tracking-widest">{devOtp}</span>
                    <span className="text-amber-600 text-xs">(auto-filled below)</span>
                  </div>
                )}
                <div className="flex gap-2">
                  <input
                    value={otp}
                    onChange={(e) => setOtp(e.target.value)}
                    placeholder="Enter 6-digit OTP"
                    maxLength={6}
                    className="flex-1 border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                  />
                  <button
                    onClick={() => verifyMutation.mutate()}
                    disabled={!otp || verifyMutation.isPending}
                    className="px-6 py-2 bg-blue-900 text-white rounded-lg hover:bg-blue-800 transition disabled:opacity-50"
                  >
                    {verifyMutation.isPending ? 'Verifying...' : 'Verify'}
                  </button>
                </div>
              </div>
            )}

            {otpMutation.isError && (
              <p className="text-red-600 text-sm">Failed to send OTP. Try again.</p>
            )}
            {verifyMutation.isError && (
              <p className="text-red-600 text-sm">Invalid OTP. Please try again.</p>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-green-700 font-medium">Verified: {email}</p>
              <span className="text-sm text-gray-500">{myComplaints.length} complaint(s)</span>
            </div>
            {myComplaints.length === 0 ? (
              <p className="text-gray-500">No complaints found for this email.</p>
            ) : (
              myComplaints.map((c) => (
                <ComplaintCard
                  key={c.id}
                  c={c}
                  expanded={expandedId === c.id}
                  onToggle={() => toggleExpand(c.id)}
                />
              ))
            )}
          </div>
        )}
      </section>
    </div>
  );
}
