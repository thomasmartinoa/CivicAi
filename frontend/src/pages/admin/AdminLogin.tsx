import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { adminLogin } from '../../services/api';

export default function AdminLogin() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const navigate = useNavigate();

  const mutation = useMutation({
    mutationFn: () => adminLogin(email, password),
    onSuccess: (res) => {
      localStorage.setItem('admin_token', res.data.access_token);
      navigate('/admin');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  return (
    <div className="max-w-md mx-auto mt-16">
      <div className="bg-white rounded-xl border border-gray-200 p-8 shadow-sm">
        <h1 className="text-2xl font-bold text-gray-900 mb-1 text-center">Admin Login</h1>
        <p className="text-gray-500 text-sm text-center mb-6">Sign in to the CivicAI admin panel</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="admin@civicai.gov"
              className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              placeholder="Enter password"
              className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
            />
          </div>

          {mutation.isError && (
            <div className="bg-red-50 border border-red-300 text-red-700 rounded-lg p-3 text-sm">
              Invalid credentials. Please try again.
            </div>
          )}

          <button
            type="submit"
            disabled={mutation.isPending}
            className="w-full py-3 bg-blue-900 text-white font-semibold rounded-lg hover:bg-blue-800 transition disabled:opacity-50"
          >
            {mutation.isPending ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
