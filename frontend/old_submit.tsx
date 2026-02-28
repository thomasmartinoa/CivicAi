import { useState, useRef } from 'react';
import { useMutation } from '@tanstack/react-query';
import { submitComplaint } from '../../services/api';

type Step = 'form' | 'confirm' | 'success';

export default function SubmitComplaint() {
  const [step, setStep] = useState<Step>('form');
  const [description, setDescription] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [trackingId, setTrackingId] = useState<string | null>(null);
  const [submittedData, setSubmittedData] = useState<any>(null);
  const [gpsLoading, setGpsLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [validationError, setValidationError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<BlobPart[]>([]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];
      const mr = new MediaRecorder(stream);
      mediaRecorderRef.current = mr;
      mr.ondataavailable = (e) => audioChunksRef.current.push(e.data);
      mr.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        setAudioBlob(blob);
        stream.getTracks().forEach((t) => t.stop());
      };
      mr.start();
      setRecording(true);
    } catch {
      alert('Microphone access denied.');
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  };

  const mutation = useMutation({
    mutationFn: (formData: FormData) => submitComplaint(formData),
    onSuccess: (res) => {
      setTrackingId(res.data.tracking_id);
      setSubmittedData(res.data);
      setStep('success');
    },
  });

  const detectGPS = () => {
    if (!navigator.geolocation) return;
    setGpsLoading(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const precLat = parseFloat(pos.coords.latitude.toFixed(6));
        const precLng = parseFloat(pos.coords.longitude.toFixed(6));
        setLat(precLat.toString());
        setLng(precLng.toString());
        // Reverse geocode to fill address field
        try {
          const res = await fetch(
            `https://nominatim.openstreetmap.org/reverse?lat=${precLat}&lon=${precLng}&format=json&addressdetails=1`,
            { headers: { 'User-Agent': 'CivicAI/1.0' } }
          );
          const data = await res.json();
          if (data?.display_name) setAddress(data.display_name);
        } catch {
          // geocoding failed, lat/lng still captured
        }
        setGpsLoading(false);
      },
      () => setGpsLoading(false),
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  const handleReview = (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError('');

    if (!address.trim()) {
      setValidationError('Address / Location is required. Use GPS Detect or enter manually.');
      return;
    }
    if (files.length === 0 && !audioBlob) {
      setValidationError('At least one attachment (photo, document, or voice recording) is required.');
      return;
    }
    setStep('confirm');
  };

  const handleConfirmSubmit = () => {
    const fd = new FormData();
    fd.append('description', description);
    fd.append('citizen_email', email);
    if (phone) fd.append('citizen_phone', phone);
    if (name) fd.append('citizen_name', name);
    fd.append('address', address);
    if (lat) fd.append('latitude', lat);
    if (lng) fd.append('longitude', lng);
    files.forEach((f) => fd.append('files', f));
    if (audioBlob) {
      fd.append('files', new File([audioBlob], 'voice_complaint.webm', { type: 'audio/webm' }));
    }
    mutation.mutate(fd);
  };

  const handleNewComplaint = () => {
    setStep('form');
    setTrackingId(null);
    setSubmittedData(null);
    setDescription('');
    setEmail('');
    setPhone('');
    setName('');
    setAddress('');
    setLat('');
    setLng('');
    setFiles([]);
    setAudioBlob(null);
    setValidationError('');
  };

  // Success screen
  if (step === 'success' && trackingId) {
    return (
      <div className="max-w-2xl mx-auto mt-12">
        <div className="bg-green-50 border border-green-300 rounded-xl p-8 text-center">
          <div className="text-green-600 text-5xl mb-4">&#10003;</div>
          <h2 className="text-2xl font-bold text-green-800 mb-2">Complaint Submitted!</h2>
          <p className="text-gray-600 mb-4">Your complaint has been received and is being processed by our AI pipeline.</p>
          <div className="bg-white rounded-lg p-4 border border-green-200 mb-6">
            <p className="text-sm text-gray-500 mb-1">Your Tracking ID</p>
            <p className="text-2xl font-mono font-bold text-blue-900">{trackingId}</p>
          </div>

          {submittedData && (
            <div className="bg-white rounded-lg border border-gray-200 p-5 text-left space-y-3 mb-6">
              <h3 className="font-semibold text-gray-800 text-sm uppercase tracking-wider border-b pb-2">Complaint Summary</h3>
              {submittedData.category && (
                <div className="flex gap-2">
                  <span className="text-xs font-semibold px-2 py-1 bg-blue-100 text-blue-800 rounded">{submittedData.category}</span>
                  {submittedData.subcategory && <span className="text-xs px-2 py-1 bg-blue-50 text-blue-600 rounded">{submittedData.subcategory}</span>}
                  {submittedData.risk_level && (
                    <span className={`text-xs font-semibold px-2 py-1 rounded ${
                      submittedData.risk_level === 'critical' ? 'bg-red-100 text-red-700' :
                      submittedData.risk_level === 'high' ? 'bg-orange-100 text-orange-700' :
                      submittedData.risk_level === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                      'bg-green-100 text-green-700'
                    }`}>Risk: {submittedData.risk_level}</span>
                  )}
                </div>
              )}
              <p className="text-sm text-gray-700">{submittedData.description}</p>
              {submittedData.address && <p className="text-xs text-gray-500">Location: {submittedData.address}</p>}
              <p className="text-xs text-gray-400">Status: {submittedData.status}</p>
            </div>
          )}

          <button
            onClick={handleNewComplaint}
            className="px-6 py-2 bg-blue-900 text-white rounded-lg hover:bg-blue-800 transition"
          >
            Submit Another Complaint
          </button>
        </div>
      </div>
    );
  }

  // Confirmation / Review screen
  if (step === 'confirm') {
    const totalFiles = files.length + (audioBlob ? 1 : 0);
    return (
      <div className="max-w-2xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Review Your Complaint</h1>
        <p className="text-gray-500 mb-6">Please review the details below before submitting.</p>

        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Description</p>
            <p className="text-gray-800 mt-1">{description}</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Email</p>
              <p className="text-gray-800 mt-1">{email}</p>
            </div>
            {phone && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Phone</p>
                <p className="text-gray-800 mt-1">{phone}</p>
              </div>
            )}
            {name && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Name</p>
                <p className="text-gray-800 mt-1">{name}</p>
              </div>
            )}
          </div>

          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Address / Location</p>
            <p className="text-gray-800 mt-1">{address}</p>
            {lat && lng && (
              <p className="text-xs text-gray-400 mt-1">GPS: {lat}, {lng}</p>
            )}
          </div>

          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Attachments ({totalFiles})</p>
            <div className="mt-2 space-y-1">
              {files.map((f, i) => (
                <div key={i} className="flex items-center gap-2 text-sm text-gray-700">
                  <span className="text-gray-400">{f.type.startsWith('image/') ? '[ img ]' : '[ file ]'}</span>
                  <span>{f.name}</span>
                  <span className="text-xs text-gray-400">({(f.size / 1024).toFixed(1)} KB)</span>
                </div>
              ))}
              {audioBlob && (
                <div className="flex items-center gap-2 text-sm text-gray-700">
                  <span className="text-gray-400">[ audio ]</span>
                  <span>voice_complaint.webm</span>
                  <span className="text-xs text-gray-400">({(audioBlob.size / 1024).toFixed(1)} KB)</span>
                </div>
              )}
            </div>
          </div>

          {/* Image previews */}
          {files.some(f => f.type.startsWith('image/')) && (
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Image Preview</p>
              <div className="flex gap-3 flex-wrap">
                {files.filter(f => f.type.startsWith('image/')).map((f, i) => (
                  <img key={i} src={URL.createObjectURL(f)} alt={f.name} className="w-24 h-24 object-cover rounded-lg border border-gray-200" />
                ))}
              </div>
            </div>
          )}
        </div>

        {mutation.isError && (
          <div className="mt-4 bg-red-50 border border-red-300 text-red-700 rounded-lg p-3 text-sm">
            Failed to submit complaint. Please try again.
          </div>
        )}

        <div className="flex gap-3 mt-6">
          <button
            onClick={() => setStep('form')}
            disabled={mutation.isPending}
            className="flex-1 py-3 border border-gray-300 text-gray-700 font-semibold rounded-lg hover:bg-gray-50 transition disabled:opacity-50"
          >
            Back to Edit
          </button>
          <button
            onClick={handleConfirmSubmit}
            disabled={mutation.isPending}
            className="flex-1 py-3 bg-blue-900 text-white font-semibold rounded-lg hover:bg-blue-800 transition disabled:opacity-50"
          >
            {mutation.isPending ? 'Submitting...' : 'Confirm & Submit'}
          </button>
        </div>
      </div>
    );
  }

  // Form screen
  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Submit a Complaint</h1>
      <p className="text-gray-500 mb-6">Describe your civic issue and we will route it to the right department using AI.</p>

      <form onSubmit={handleReview} className="space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description *</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
            rows={5}
            placeholder="Describe the issue in detail..."
            className="w-full border border-gray-300 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email *</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="your@email.com"
              className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Phone</label>
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+91 98765 43210"
              className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your name (optional)"
            className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Address / Location *</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="Street address or landmark (use GPS Detect)"
              className={`flex-1 border rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none ${
                validationError && !address.trim() ? 'border-red-400 bg-red-50' : 'border-gray-300'
              }`}
            />
            <button
              type="button"
              onClick={detectGPS}
              disabled={gpsLoading}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition disabled:opacity-50 whitespace-nowrap"
            >
              {gpsLoading ? 'Detecting...' : 'GPS Detect'}
            </button>
          </div>
          {lat && lng && (
            <p className="text-xs text-green-600 mt-1 font-medium">📍 GPS captured: {lat}, {lng}{address ? ' — address filled above' : ''}</p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Attachments *</label>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept="image/*,video/*,.pdf,.doc,.docx"
            onChange={(e) => setFiles(Array.from(e.target.files || []))}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className={`px-4 py-2 border-2 border-dashed rounded-lg transition w-full ${
              validationError && files.length === 0 && !audioBlob
                ? 'border-red-400 text-red-500 bg-red-50'
                : 'border-gray-300 text-gray-500 hover:border-blue-400 hover:text-blue-500'
            }`}
          >
            {files.length > 0 ? `${files.length} file(s) selected` : 'Click to upload photos or documents'}
          </button>
          {files.length > 0 && (
            <div className="mt-2 flex gap-2 flex-wrap">
              {files.map((f, i) => (
                <span key={i} className="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded">{f.name}</span>
              ))}
            </div>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Voice Complaint</label>
          <div className="flex items-center gap-3">
            {!recording ? (
              <button
                type="button"
                onClick={startRecording}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition"
              >
                <span className="w-3 h-3 rounded-full bg-white inline-block"></span>
                Record Audio
              </button>
            ) : (
              <button
                type="button"
                onClick={stopRecording}
                className="flex items-center gap-2 px-4 py-2 bg-gray-800 text-white rounded-lg hover:bg-gray-900 transition animate-pulse"
              >
                <span className="w-3 h-3 rounded bg-red-500 inline-block"></span>
                Stop Recording
              </button>
            )}
            {audioBlob && !recording && (
              <div className="flex items-center gap-2">
                <audio controls src={URL.createObjectURL(audioBlob)} className="h-8" />
                <button
                  type="button"
                  onClick={() => setAudioBlob(null)}
                  className="text-xs text-red-500 hover:underline"
                >
                  Remove
                </button>
              </div>
            )}
          </div>
        </div>

        {validationError && (
          <div className="bg-red-50 border border-red-300 text-red-700 rounded-lg p-3 text-sm">
            {validationError}
          </div>
        )}

        <button
          type="submit"
          className="w-full py-3 bg-blue-900 text-white font-semibold rounded-lg hover:bg-blue-800 transition"
        >
          Review & Submit
        </button>
      </form>
    </div>
  );
}
