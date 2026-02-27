import { useState, useRef } from 'react';
import { useMutation } from '@tanstack/react-query';
import { submitComplaint } from '../../services/api';

export default function SubmitComplaint() {
  const [description, setDescription] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [trackingId, setTrackingId] = useState<string | null>(null);
  const [gpsLoading, setGpsLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
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
      setDescription('');
      setEmail('');
      setPhone('');
      setName('');
      setAddress('');
      setLat('');
      setLng('');
      setFiles([]);
    },
  });

  const detectGPS = () => {
    if (!navigator.geolocation) return;
    setGpsLoading(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLat(pos.coords.latitude.toString());
        setLng(pos.coords.longitude.toString());
        setGpsLoading(false);
      },
      () => setGpsLoading(false)
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const fd = new FormData();
    fd.append('description', description);
    fd.append('citizen_email', email);
    if (phone) fd.append('citizen_phone', phone);
    if (name) fd.append('citizen_name', name);
    if (address) fd.append('address', address);
    if (lat) fd.append('latitude', lat);
    if (lng) fd.append('longitude', lng);
    files.forEach((f) => fd.append('files', f));
    if (audioBlob) {
      fd.append('files', new File([audioBlob], 'voice_complaint.webm', { type: 'audio/webm' }));
    }
    mutation.mutate(fd);
  };

  if (trackingId) {
    return (
      <div className="max-w-lg mx-auto mt-12">
        <div className="bg-green-50 border border-green-300 rounded-xl p-8 text-center">
          <div className="text-green-600 text-5xl mb-4">&#10003;</div>
          <h2 className="text-2xl font-bold text-green-800 mb-2">Complaint Submitted!</h2>
          <p className="text-gray-600 mb-4">Your complaint has been received and is being processed by our AI pipeline.</p>
          <div className="bg-white rounded-lg p-4 border border-green-200">
            <p className="text-sm text-gray-500 mb-1">Your Tracking ID</p>
            <p className="text-2xl font-mono font-bold text-blue-900">{trackingId}</p>
          </div>
          <button
            onClick={() => setTrackingId(null)}
            className="mt-6 px-6 py-2 bg-blue-900 text-white rounded-lg hover:bg-blue-800 transition"
          >
            Submit Another Complaint
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Submit a Complaint</h1>
      <p className="text-gray-500 mb-6">Describe your civic issue and we will route it to the right department using AI.</p>

      <form onSubmit={handleSubmit} className="space-y-5">
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
          <label className="block text-sm font-medium text-gray-700 mb-1">Address / Location</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="Street address or landmark"
              className="flex-1 border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
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
            <p className="text-xs text-gray-500 mt-1">Coordinates: {lat}, {lng}</p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Attachments</label>
          <input
            ref={fileRef}
            type="file"
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files || []))}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="px-4 py-2 border-2 border-dashed border-gray-300 rounded-lg text-gray-500 hover:border-blue-400 hover:text-blue-500 transition w-full"
          >
            {files.length > 0 ? `${files.length} file(s) selected` : 'Click to upload photos or documents'}
          </button>
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

        {mutation.isError && (
          <div className="bg-red-50 border border-red-300 text-red-700 rounded-lg p-3 text-sm">
            Failed to submit complaint. Please try again.
          </div>
        )}

        <button
          type="submit"
          disabled={mutation.isPending}
          className="w-full py-3 bg-blue-900 text-white font-semibold rounded-lg hover:bg-blue-800 transition disabled:opacity-50"
        >
          {mutation.isPending ? 'Submitting...' : 'Submit Complaint'}
        </button>
      </form>
    </div>
  );
}
