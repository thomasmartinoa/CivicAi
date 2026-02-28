import { Link, Outlet, useLocation } from 'react-router-dom';

export default function Layout() {
  const location = useLocation();
  const isActive = (path: string) =>
    location.pathname.startsWith(path) ? 'bg-blue-700' : '';

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-blue-900 text-white shadow-lg">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link to="/" className="text-xl font-bold">CivicAI</Link>
          <div className="flex gap-2">
            <Link to="/" className={`px-3 py-1 rounded ${isActive('/submit') || location.pathname === '/' ? 'bg-blue-700' : ''}`}>Submit Complaint</Link>
            <Link to="/track" className={`px-3 py-1 rounded ${isActive('/track')}`}>Track</Link>
            <Link to="/dashboard" className={`px-3 py-1 rounded ${isActive('/dashboard')}`}>Public Dashboard</Link>
            <Link to="/pricing" className={`px-3 py-1 rounded ${isActive('/pricing')}`}>Pricing</Link>
            <Link to="/admin" className={`px-3 py-1 rounded ${isActive('/admin')}`}>Admin</Link>
          </div>
        </div>
      </nav>
      <main className="max-w-7xl mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
