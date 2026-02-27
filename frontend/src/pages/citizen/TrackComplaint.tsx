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

function ComplaintCard({ c }: { c: Complaint }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="font-mono text-sm text-gray-500">{c.tracking_id}</span>
        <span className={`px-3 py-1 rounded-full text-xs font-medium ${statusColor[c.status] || 'bg-gray-100 text-gray-700'}`}>
          {c.status}
        </span>
      </div>
      <p className="text-gray-800 mb-3">{c.description}</p>
      <div className="flex flex-wrap gap-2 text-xs">
        {c.category && (
          <span className="bg-blue-50 text-blue-700 px-2 py-1 rounded">{c.category}</span>
        )}
        {c.subcategory && (
          <span className="bg-blue-50 text-blue-600 px-2 py-1 rounded">{c.subcategory}</span>
        )}
        {c.risk_level && (
          <span className={`px-2 py-1 rounded ${riskColor[c.risk_level] || ''}`}>Risk: {c.risk_level}</span>
        )}
        {c.priority_score !== null && (
          <span className="bg-gray-100 text-gray-600 px-2 py-1 rounded">Priority: {c.priority_score}</span>
        )}
      </div>
      {c.address && <p className="text-xs text-gray-400 mt-2">{c.address}</p>}
      <p className="text-xs text-gray-400 mt-1">Created: {new Date(c.created_at).toLocaleString()}</p>
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

  const trackMutation = useMutation({
    mutationFn: () => trackComplaint(trackingId),
  });

  const otpMutation = useMutation({
    mutationFn: () => requestOTP(email),
    onSuccess: () => setOtpSent(true),
  });

  const verifyMutation = useMutation({
    mutationFn: () => verifyOTP(email, otp),
    onSuccess: async () => {
      setVerified(true);
      const res = await getMyComplaints(email);
      setMyComplaints(res.data);
    },
  });

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
            <ComplaintCard c={trackMutation.data.data} />
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
              myComplaints.map((c) => <ComplaintCard key={c.id} c={c} />)
            )}
          </div>
        )}
      </section>
    </div>
  );
}
