import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { trackComplaint, requestOTP, verifyOTP, getMyComplaints, rateComplaint, verifyComplaintFixed } from '../../services/api';
import type { Complaint } from '../../types';

const STATUS_STEPS = [
  { key: 'submitted',   label: 'Submitted',   desc: 'Complaint received' },
  { key: 'validated',   label: 'Verified',    desc: 'Details validated by AI' },
  { key: 'classified',  label: 'AI Processed',desc: 'Category & risk assessed' },
  { key: 'assigned',    label: 'Assigned',    desc: 'Contractor auto-assigned' },
  { key: 'grouped',     label: 'Assigned',    desc: 'Grouped with nearby issues' },
  { key: 'in_progress', label: 'In Progress', desc: 'Work underway' },
  { key: 'resolved',    label: 'Resolved',    desc: 'Issue fixed' },
  { key: 'closed',      label: 'Closed',      desc: 'Confirmed complete' },
];

// Ordered pipeline stages for the visual tracker
const PIPELINE_STAGES = [
  { key: 'submitted',   label: 'Submitted' },
  { key: 'validated',   label: 'Verified' },
  { key: 'classified',  label: 'AI Processed' },
  { key: 'assigned',    label: 'Assigned' },
  { key: 'in_progress', label: 'In Progress' },
  { key: 'resolved',    label: 'Resolved' },
];

const STATUS_ORDER = ['submitted', 'validated', 'classified', 'routed', 'grouped', 'assigned', 'in_progress', 'escalated', 'resolved', 'closed'];

function getStepIndex(status: string): number {
  const pipelineKeys = PIPELINE_STAGES.map(s => s.key);
  const idx = pipelineKeys.indexOf(status);
  if (idx !== -1) return idx;
  // map aliases
  if (['routed', 'work_order_created'].includes(status)) return 3;
  if (['grouped', 'escalated'].includes(status)) return 3;
  if (status === 'closed') return 5;
  return 0;
}

const riskColor: Record<string, string> = {
  low: 'bg-green-100 text-green-700',
  medium: 'bg-yellow-100 text-yellow-700',
  high: 'bg-orange-100 text-orange-700',
  critical: 'bg-red-100 text-red-700',
};

const statusBadge: Record<string, string> = {
  submitted: 'bg-gray-100 text-gray-700',
  assigned: 'bg-purple-100 text-purple-800',
  in_progress: 'bg-orange-100 text-orange-800',
  resolved: 'bg-green-100 text-green-800',
  closed: 'bg-gray-200 text-gray-600',
  escalated: 'bg-red-100 text-red-700',
  grouped: 'bg-blue-100 text-blue-800',
};

function ProgressTimeline({ status }: { status: string }) {
  const currentIdx = getStepIndex(status);
  return (
    <div className="mt-4 mb-2">
      <div className="flex items-center">
        {PIPELINE_STAGES.map((stage, idx) => {
          const done = idx <= currentIdx;
          const active = idx === currentIdx;
          return (
            <div key={stage.key} className="flex items-center flex-1 last:flex-none">
              <div className="flex flex-col items-center">
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-colors ${
                  done
                    ? 'bg-blue-900 border-blue-900 text-white'
                    : 'bg-white border-gray-300 text-gray-400'
                } ${active ? 'ring-2 ring-blue-300 ring-offset-1' : ''}`}>
                  {done ? (idx < currentIdx ? '\u2713' : (idx + 1)) : (idx + 1)}
                </div>
                <span className={`mt-1 text-xs text-center leading-tight ${done ? 'text-blue-900 font-medium' : 'text-gray-400'}`}>
                  {stage.label}
                </span>
              </div>
              {idx < PIPELINE_STAGES.length - 1 && (
                <div className={`flex-1 h-0.5 mx-1 mt-[-12px] transition-colors ${idx < currentIdx ? 'bg-blue-900' : 'bg-gray-200'}`} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ComplaintCard({ c: initialC, expanded, onToggle }: { c: Complaint; expanded: boolean; onToggle: () => void }) {
  const [c, setC] = useState<Complaint>(initialC);
  const stepDesc = STATUS_STEPS.find(s => s.key === c.status)?.desc || 'Processing';
  const images = (c.media || []).filter(m => m.media_type === 'image');

  const verifyMutation = useMutation({
    mutationFn: (isFixed: boolean) => verifyComplaintFixed(c.tracking_id, isFixed),
    onSuccess: (res, isFixed) => {
      setC(prev => ({
        ...prev,
        status: res.data.status,
        verified_fixed: isFixed,
      }));
    },
  });

  const showVerifyBanner = c.status === 'resolved' && c.verified_fixed === null;
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm cursor-pointer" onClick={onToggle}>
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-sm font-semibold text-blue-900">{c.tracking_id}</span>
        <span className={`px-3 py-1 rounded-full text-xs font-medium ${statusBadge[c.status] || 'bg-gray-100 text-gray-700'}`}>
          {c.status.replace(/_/g, ' ')}
        </span>
      </div>

      {images.length > 0 && (
        <div className="flex gap-2 mt-2 mb-3 overflow-x-auto pb-1">
          {images.map((m, i) => (
            <img
              key={i}
              src={`http://localhost:8000/${m.file_path}`}
              alt={m.original_filename || 'complaint image'}
              className="h-28 w-40 object-cover rounded-lg border border-gray-200 flex-shrink-0"
            />
          ))}
        </div>
      )}

      <ProgressTimeline status={c.status} />

      <p className="text-xs text-gray-500 mb-3 italic">{stepDesc}</p>

      {showVerifyBanner && (
        <div className="mb-4 bg-amber-50 border border-amber-300 rounded-xl p-4" onClick={(e) => e.stopPropagation()}>
          <p className="font-semibold text-amber-800 mb-1">Was your issue actually fixed?</p>
          <p className="text-sm text-amber-700 mb-3">The contractor marked this as resolved. Please confirm if the problem has been genuinely fixed.</p>
          <div className="flex gap-3">
            <button
              onClick={() => verifyMutation.mutate(true)}
              disabled={verifyMutation.isPending}
              className="flex-1 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 transition disabled:opacity-50"
            >
              Yes, it's fixed
            </button>
            <button
              onClick={() => verifyMutation.mutate(false)}
              disabled={verifyMutation.isPending}
              className="flex-1 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 transition disabled:opacity-50"
            >
              No, still broken
            </button>
          </div>
          {verifyMutation.isError && (
            <p className="text-red-600 text-xs mt-2">Failed to submit. Please try again.</p>
          )}
        </div>
      )}

      {c.reopen_count > 0 && (
        <div className="mb-3 text-xs flex items-center gap-1 text-orange-600 bg-orange-50 border border-orange-200 rounded-lg px-3 py-2">
          <span>This complaint was reopened <strong>{c.reopen_count}</strong> time{c.reopen_count > 1 ? 's' : ''} due to unsatisfactory resolution.</span>
        </div>
      )}
      <p className="text-gray-800 mb-3 text-sm">{c.description}</p>

      <div className="flex flex-wrap gap-2 text-xs">
        {c.category && (
          <span className="bg-blue-50 text-blue-700 px-2 py-1 rounded font-medium">{c.category}</span>
        )}
        {c.subcategory && (
          <span className="bg-blue-50 text-blue-600 px-2 py-1 rounded">{c.subcategory}</span>
        )}
        {c.risk_level && (
          <span className={`px-2 py-1 rounded font-medium ${riskColor[c.risk_level] || ''}`}>
            {c.risk_level.toUpperCase()} risk
          </span>
        )}
        {c.priority_score !== null && (
          <span className="bg-gray-100 text-gray-600 px-2 py-1 rounded">Priority score: {c.priority_score}</span>
        )}
      </div>

      {c.address && <p className="text-xs text-gray-400 mt-3">{c.address}</p>}
      <p className="text-xs text-gray-400 mt-1">Submitted: {new Date(c.created_at).toLocaleString()}</p>

      {['resolved', 'closed', 'in_progress'].includes(c.status) && (
        <div onClick={(e) => e.stopPropagation()}>
          <SatisfactionRating trackingId={c.tracking_id} existingRating={(c as any).satisfaction_rating} />
        </div>
      )}
    </div>
  );
}

function SatisfactionRating({ trackingId, existingRating }: { trackingId: string; existingRating?: number | null }) {
  const [hovered, setHovered] = useState(0);
  const [selected, setSelected] = useState(existingRating || 0);
  const [submitted, setSubmitted] = useState(!!existingRating);
  const [comment, setComment] = useState('');

  const rateMutation = useMutation({
    mutationFn: () => rateComplaint(trackingId, selected, comment),
    onSuccess: () => setSubmitted(true),
  });

  if (submitted || existingRating) {
    return (
      <div className="mt-4 pt-3 border-t border-gray-100">
        <p className="text-xs text-green-700 font-medium">Thank you for your feedback!</p>
        <div className="flex gap-0.5 mt-1">
          {[1,2,3,4,5].map(s => (
            <span key={s} className={`text-lg ${s <= (existingRating || selected) ? 'text-yellow-400' : 'text-gray-200'}`}>*</span>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="mt-4 pt-3 border-t border-gray-100">
      <p className="text-xs font-medium text-gray-600 mb-2">How satisfied are you with the resolution?</p>
      <div className="flex gap-0.5 mb-2">
        {[1,2,3,4,5].map(s => (
          <button
            key={s}
            onMouseEnter={() => setHovered(s)}
            onMouseLeave={() => setHovered(0)}
            onClick={() => setSelected(s)}
            className={`text-2xl transition-colors ${s <= (hovered || selected) ? 'text-yellow-400' : 'text-gray-200'} hover:scale-110`}
          >*</button>
        ))}
      </div>
      {selected > 0 && (
        <div className="space-y-2">
          <input
            value={comment}
            onChange={e => setComment(e.target.value)}
            placeholder="Optional comment..."
            className="w-full text-xs border border-gray-200 rounded px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
          <button
            onClick={() => rateMutation.mutate()}
            disabled={rateMutation.isPending}
            className="px-4 py-1.5 bg-blue-900 text-white text-xs rounded hover:bg-blue-800 disabled:opacity-50"
          >
            {rateMutation.isPending ? 'Submitting...' : 'Submit rating'}
          </button>
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
