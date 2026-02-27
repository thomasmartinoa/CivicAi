import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000' });

// Attach admin token to every /admin request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token) {
    const url = config.url ?? '';
    if (url.startsWith('/admin') || url.includes('/admin/')) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// On 401/403 clear the stale token so the UI re-guards correctly
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 || error?.response?.status === 403) {
      const url = error?.config?.url ?? '';
      const isAdminRoute = (url.startsWith('/admin') || url.includes('/admin/'));
      const isLoginRoute = url.includes('/admin/login');
      if (isAdminRoute && !isLoginRoute) {
        localStorage.removeItem('admin_token');
        window.location.href = '/admin/login';
      }
    }
    return Promise.reject(error);
  }
);

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
export const getPerformanceMetrics = () => api.get('/admin/analytics/performance');
export const getContractors = () => api.get('/admin/contractors');
export const seedDatabase = () => api.post('/admin/seed');
export default api;
