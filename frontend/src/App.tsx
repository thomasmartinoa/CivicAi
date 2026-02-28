import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import SubmitComplaint from './pages/citizen/SubmitComplaint';
import TrackComplaint from './pages/citizen/TrackComplaint';
import PublicDashboard from './pages/public/PublicDashboard';
import AdminLogin from './pages/admin/AdminLogin';
import AdminDashboard from './pages/admin/AdminDashboard';
import AdminComplaints from './pages/admin/AdminComplaints';
import AdminWorkOrders from './pages/admin/AdminWorkOrders';
import Pricing from './pages/Pricing';

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/" element={<Layout />}>
            <Route index element={<SubmitComplaint />} />
            <Route path="track" element={<TrackComplaint />} />
            <Route path="dashboard" element={<PublicDashboard />} />
            <Route path="admin/login" element={<AdminLogin />} />
            <Route path="admin" element={<AdminDashboard />} />
            <Route path="admin/complaints" element={<AdminComplaints />} />
            <Route path="admin/work-orders" element={<AdminWorkOrders />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
