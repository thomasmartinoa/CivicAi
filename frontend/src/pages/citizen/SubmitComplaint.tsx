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
      setValidationError('Address / Location is required. Use Location Detect or enter manually.');
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
      <div className="max-w-4xl mx-auto my-12 bg-white rounded-3xl shadow-[0_8px_30px_rgb(0,0,0,0.04)] sm:p-10 flex flex-col items-center border border-gray-100 p-6">
        <div className="w-16 h-16 bg-blue-100 text-blue-600 rounded-full flex justify-center items-center text-3xl mb-6">
          <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
        </div>
        <h2 className="text-3xl font-bold text-gray-900 mb-3 text-center">Complaint Submitted Successfully!</h2>
        <p className="text-gray-500 mb-8 text-center max-w-lg">Your complaint has been safely received. Our AI will now classify, assess, and route it to the proper department.</p>
        
        <div className="bg-[#FAFAFA] border border-gray-100 rounded-2xl w-full max-w-md p-6 mb-8 text-center">
          <p className="text-sm font-medium text-gray-500 mb-2 uppercase tracking-wide">Tracking ID</p>
          <div className="text-3xl font-mono font-bold text-blue-600 tracking-tight">{trackingId}</div>
          <button className="mt-4 text-sm text-blue-600 font-medium hover:underline flex items-center justify-center gap-1 mx-auto" onClick={() => navigator.clipboard.writeText(trackingId)}>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>
            Copy Tracking ID
          </button>
        </div>

        <button onClick={handleNewComplaint} className="px-8 py-3 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 transition">
          Submit Another Request
        </button>
      </div>
    );
  }

  // Confirmation screen
  if (step === 'confirm') {
    const totalFiles = files.length + (audioBlob ? 1 : 0);
    return (
      <div className="max-w-4xl mx-auto my-6 sm:my-10 bg-white rounded-3xl shadow-[0_8px_30px_rgb(0,0,0,0.04)] flex overflow-hidden border border-gray-100">
        <div className="flex-1 p-6 sm:p-12">
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Review Details</h1>
            <div className="flex items-center text-sm font-medium text-blue-600 bg-blue-50 w-fit px-3 py-1 rounded-full">
              Final Step (2/2)
            </div>
          </div>
          
          <div className="space-y-6">
            <div className="bg-[#FAFAFA] rounded-2xl p-5 border border-gray-100">
               <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Description</p>
               <p className="text-gray-800 text-sm leading-relaxed">{description}</p>
            </div>
            
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="bg-[#FAFAFA] rounded-2xl p-5 border border-gray-100">
                 <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Applicant Info</p>
                 <p className="text-sm font-medium text-gray-900">{name || 'Anonymous'}</p>
                 <p className="text-sm text-gray-600">{email}</p>
                 {phone && <p className="text-sm text-gray-600">{phone}</p>}
              </div>

              <div className="bg-[#FAFAFA] rounded-2xl p-5 border border-gray-100">
                 <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Location</p>
                 <p className="text-sm text-gray-800 line-clamp-2">{address}</p>
                 {lat && lng && <p className="text-xs text-blue-600 mt-2 font-medium">GPS Coordinates attached</p>}
              </div>
            </div>
            
            <div className="bg-[#FAFAFA] rounded-2xl p-5 border border-gray-100">
               <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Attachments & Media ({totalFiles})</p>
               <div className="flex flex-wrap gap-2">
                 {files.map((f, i) => (
                    <div key={i} className="flex items-center gap-2 bg-white border border-gray-200 px-3 py-2 rounded-xl text-sm">
                      <span className="text-blue-500">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path></svg>
                      </span>
                      <span className="truncate max-w-[120px] text-gray-700">{f.name}</span>
                    </div>
                  ))}
                  {audioBlob && (
                    <div className="flex items-center gap-2 bg-blue-50 border border-blue-100 px-3 py-2 rounded-xl text-sm text-blue-700">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"></path></svg>
                      <span>Voice Note</span>
                    </div>
                  )}
               </div>
            </div>

            {mutation.isError && (
              <div className="bg-red-50 text-red-600 p-4 rounded-xl text-sm font-medium border border-red-100">
                Failed to submit complaint. Please check your connection and try again.
              </div>
            )}
            
            <div className="flex gap-4 pt-6 flex-col-reverse sm:flex-row">
              <button
                onClick={() => setStep('form')}
                disabled={mutation.isPending}
                className="px-6 py-3 font-medium text-gray-600 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition sm:min-w-[120px]"
              >
                Go Back
              </button>
              <button
                onClick={handleConfirmSubmit}
                disabled={mutation.isPending}
                className="flex-1 py-3 bg-blue-600 text-white font-medium rounded-xl hover:bg-blue-700 transition disabled:opacity-70 flex justify-center items-center gap-2 shadow-sm shadow-blue-200"
              >
                {mutation.isPending ? 'Processing...' : 'Submit Request'}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Form screen
  return (
    <div className="max-w-5xl mx-auto my-6 sm:my-10 bg-white rounded-[2rem] shadow-[0_8px_30px_rgb(0,0,0,0.04)] flex flex-col md:flex-row overflow-hidden border border-gray-100">
      <div className="flex-1 p-6 sm:p-12 min-w-0">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">New Complaint</h1>
          <div className="flex items-center text-sm font-medium text-blue-600 bg-blue-50 w-fit px-3 py-1 rounded-full">
            Issue Information (Step 1/2)
          </div>
        </div>

        <form onSubmit={handleReview} className="space-y-6">
          <div className="grid grid-cols-1 gap-6">
            <div>
              <label className="block text-sm font-semibold text-gray-900 mb-2">Description *</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                required
                rows={4}
                placeholder="Describe the issue in detail..."
                className="w-full bg-[#FAFAFA] border border-gray-200 rounded-xl px-4 py-3 text-sm focus:bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition resize-none"
              />
            </div>
            
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              <div>
                <label className="block text-sm font-semibold text-gray-900 mb-2">Email Address *</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  placeholder="your@email.com"
                  className="w-full bg-[#FAFAFA] border border-gray-200 rounded-xl px-4 py-3 text-sm focus:bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition"
                />
              </div>
              <div>
                <label className="block text-sm font-semibold text-gray-900 mb-2">Phone Number</label>
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+1 (555) 000-0000"
                  className="w-full bg-[#FAFAFA] border border-gray-200 rounded-xl px-4 py-3 text-sm focus:bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-900 mb-2">Full Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="John Doe"
                className="w-full bg-[#FAFAFA] border border-gray-200 rounded-xl px-4 py-3 text-sm focus:bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition"
              />
            </div>

            <div>
              <div className="flex justify-between items-end mb-2">
                <label className="block text-sm font-semibold text-gray-900">Location *</label>
                <button type="button" onClick={detectGPS} disabled={gpsLoading} className="text-xs font-medium text-blue-600 hover:text-blue-700 flex items-center gap-1 bg-blue-50 px-2 py-1 rounded-md transition">
                  {gpsLoading ? 'Locating...' : 'Use Current Location'}
                </button>
              </div>
              <input
                type="text"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="Enter street address or drag map marker"
                className={`w-full bg-[#FAFAFA] border rounded-xl px-4 py-3 text-sm focus:bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition ${validationError && !address.trim() ? 'border-red-400 bg-red-50' : 'border-gray-200'}`}
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-gray-900 mb-2">Photos & Documents *</label>
              
              <div className={`p-6 border-2 border-dashed rounded-2xl flex flex-col items-center justify-center text-center transition ${validationError && files.length === 0 && !audioBlob ? 'border-red-300 bg-red-50' : 'border-gray-200 bg-[#FAFAFA] hover:bg-gray-50'}`}>
                <div className="w-12 h-12 mb-3 rounded-full bg-blue-50 flex items-center justify-center text-blue-600">
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
                </div>
                <p className="text-sm font-medium text-gray-900 mb-1">Click or drag files here</p>
                <p className="text-xs text-gray-500 mb-4">Supported formats: JPG, PNG, PDF</p>
                
                <input ref={fileRef} type="file" multiple accept="image/*,video/*,.pdf,.doc,.docx" onChange={(e) => setFiles(Array.from(e.target.files || []))} className="hidden" />
                
                <div className="flex gap-3">
                  <button type="button" onClick={() => fileRef.current?.click()} className="px-5 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 shadow-sm transition">
                    Browse Files
                  </button>
                  <button type="button" onClick={recording ? stopRecording : startRecording} className={`px-5 py-2 text-sm font-medium rounded-lg shadow-sm transition flex items-center gap-2 ${recording ? 'bg-red-600 text-white hover:bg-red-700 animate-pulse' : 'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50'}`}>
                    {recording ? 'Stop Rec' : 'Record Voice'}
                  </button>
                </div>
              </div>

              {(files.length > 0 || audioBlob) && (
                <div className="mt-4 flex gap-2 flex-wrap">
                  {files.map((f, i) => (
                    <div key={i} className="px-3 py-1.5 bg-blue-50 text-blue-700 text-xs font-medium rounded-lg flex items-center gap-2 border border-blue-100">
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                      {f.name}
                    </div>
                  ))}
                  {audioBlob && (
                    <div className="px-3 py-1.5 bg-purple-50 text-purple-700 text-xs font-medium rounded-lg flex items-center gap-2 border border-purple-100">
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"></path></svg>
                      Voice Note Attached
                      <button type="button" onClick={() => setAudioBlob(null)} className="ml-1 text-purple-400 hover:text-purple-600">&times;</button>
                    </div>
                  )}
                </div>
              )}
            </div>

            {validationError && (
              <div className="text-sm font-medium text-red-600 bg-red-50 border border-red-100 p-3 rounded-xl flex items-start gap-2">
                {validationError}
              </div>
            )}
            
            <div className="pt-2 border-t border-gray-100">
              <button type="submit" className="w-full sm:w-auto sm:ml-auto px-8 py-3.5 bg-blue-600 text-white font-medium text-sm rounded-xl hover:bg-blue-700 transition shadow-sm shadow-blue-200 block text-center">
                Review Application
              </button>
            </div>
          </div>
        </form>
      </div>

      <div className="hidden md:block w-[340px] bg-[#F9FAFB] p-8 border-l border-gray-100">
        <div className="mb-8">
          <h3 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">Tips for Fast Resolution</h3>
          <ul className="space-y-4">
            <li className="flex items-start gap-3">
              <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center shrink-0 mt-0.5"><span className="text-xs font-bold">1</span></div>
              <p className="text-sm text-gray-600 leading-relaxed">Provide <strong className="text-gray-800">clear photos</strong> showing the full extent of the issue.</p>
            </li>
            <li className="flex items-start gap-3">
              <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center shrink-0 mt-0.5"><span className="text-xs font-bold">2</span></div>
              <p className="text-sm text-gray-600 leading-relaxed">Use <strong className="text-gray-800">Location GPS</strong> so crews can navigate directly to the exact spot.</p>
            </li>
            <li className="flex items-start gap-3">
              <div className="w-6 h-6 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center shrink-0 mt-0.5"><span className="text-xs font-bold">3</span></div>
              <p className="text-sm text-gray-600 leading-relaxed">Consider leaving a <strong className="text-gray-800">Voice Note</strong> to explain complex situations.</p>
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
