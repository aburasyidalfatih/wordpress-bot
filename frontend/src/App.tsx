import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useEffect, useState, lazy, Suspense } from 'react';
import { apiFetch } from './lib/api';
import Layout from './components/Layout';
import { Toaster } from './components/ui/sonner';
import { SiteProvider } from './contexts/SiteContext';

// Lazy loaded pages
const Landing = lazy(() => import('./pages/Landing'));
const Login = lazy(() => import('./pages/Login'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Settings = lazy(() => import('./pages/Settings'));
const Sites = lazy(() => import('./pages/Sites'));
const Prompts = lazy(() => import('./pages/Prompts'));
const Research = lazy(() => import('./pages/Research'));
const Monitor = lazy(() => import('./pages/Monitor'));
const Queue = lazy(() => import('./pages/Queue'));
const Billing = lazy(() => import('./pages/Billing'));
const AdminDashboard = lazy(() => import('./pages/AdminDashboard'));

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
  const [userRole, setUserRole] = useState<string>('user');

  useEffect(() => {
    apiFetch('/api/auth/status')
      .then(res => {
        if (!res.ok) throw new Error('Not auth');
        return res.json();
      })
      .then(data => {
        setIsAuthenticated(data.authenticated);
        if (data.role) setUserRole(data.role);
      })
      .catch(() => setIsAuthenticated(false));
  }, []);

  if (isAuthenticated === null) {
    return <div className="flex h-screen items-center justify-center">Loading...</div>;
  }

  return (
    <SiteProvider>
      <BrowserRouter>
        <Suspense fallback={<div className="flex h-screen items-center justify-center">Loading page...</div>}>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={isAuthenticated ? <Navigate to="/dashboard" /> : <Login setIsAuthenticated={setIsAuthenticated} setUserRole={setUserRole} />} />
            <Route path="/register" element={<Navigate to="/login" replace />} />
            
            {/* Authenticated Routes with Layout */}
            <Route path="/dashboard" element={isAuthenticated ? <Layout><Dashboard /></Layout> : <Navigate to="/login" />} />
            <Route path="/sites" element={isAuthenticated ? <Layout><Sites /></Layout> : <Navigate to="/login" />} />
            <Route path="/settings" element={isAuthenticated ? <Layout><Settings /></Layout> : <Navigate to="/login" />} />
            <Route path="/prompts" element={isAuthenticated ? <Layout><Prompts /></Layout> : <Navigate to="/login" />} />
            <Route path="/research" element={isAuthenticated ? <Layout><Research /></Layout> : <Navigate to="/login" />} />
            <Route path="/queue" element={isAuthenticated ? <Layout><Queue /></Layout> : <Navigate to="/login" />} />
            <Route path="/monitor" element={isAuthenticated ? <Layout><Monitor /></Layout> : <Navigate to="/login" />} />
            <Route path="/billing" element={isAuthenticated ? <Layout><Billing /></Layout> : <Navigate to="/login" />} />
            <Route path="/admin" element={isAuthenticated && userRole === 'admin' ? <Layout><AdminDashboard /></Layout> : <Navigate to="/dashboard" />} />
          </Routes>
        </Suspense>
        <Toaster position="top-center" richColors />
      </BrowserRouter>
    </SiteProvider>
  );
}

export default App;
