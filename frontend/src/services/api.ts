import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000' });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token && config.url?.startsWith('/admin')) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const submitComplaint = (formData: FormData) => api.post('/complaints/', formData);
export const trackComplaint = (trackingId: string) => api.get(`/complaints/track/${trackingId}`);
export const requestOTP = (email: string) => api.post('/complaints/verify-email', { email });
export const verifyOTP = (email: string, otp: string) => api.post('/complaints/verify-otp', { email, otp });
export const getMyComplaints = (email: string) => api.get(`/complaints/my?email=${email}`);
export const getPublicDashboard = (tenantId?: string) => api.get('/public/dashboard', { params: { tenant_id: tenantId } });
export const adminLogin = (email: string, password: string) => api.post('/admin/login', { email, password });
export const getAdminComplaints = (params?: Record<string, string>) => api.get('/admin/complaints', { params });
export const updateComplaint = (id: string, data: Record<string, unknown>) => api.patch(`/admin/complaints/${id}`, data);
export const getWorkOrders = (status?: string) => api.get('/admin/work-orders', { params: { status } });
export const updateWorkOrder = (id: string, data: Record<string, unknown>) => api.patch(`/admin/work-orders/${id}`, data);
export const getAnalytics = () => api.get('/admin/analytics');
export const getContractors = () => api.get('/admin/contractors');
export const seedDatabase = () => api.post('/admin/seed');
export default api;
