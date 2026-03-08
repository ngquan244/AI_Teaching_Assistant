/**
 * Application Router
 * Handles routing with authentication protection
 */
import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import { LoginPage, SignupPage, AdminLayout, AdminDashboard, AdminUsers, AdminJobs, AdminPanels, AdminModels, AdminTools, AdminInviteCodes } from './pages';
import { Loader2 } from 'lucide-react';

// Import the main app content (existing dashboard)
import App from './App';

/**
 * Protected Route wrapper
 * Redirects to login if not authenticated
 */
const ProtectedRoute: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  
  if (isLoading) {
    return (
      <div className="loading-screen">
        <Loader2 className="spin" size={48} />
        <p>Loading...</p>
      </div>
    );
  }
  
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  
  return <Outlet />;
};

/**
 * Admin Route wrapper
 * Requires authentication + ADMIN role
 */
const AdminRoute: React.FC = () => {
  const { isAuthenticated, isLoading, user } = useAuth();

  if (isLoading) {
    return (
      <div className="loading-screen">
        <Loader2 className="spin" size={48} />
        <p>Loading...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (user?.role !== 'ADMIN') {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
};

/**
 * Public Route wrapper
 * Redirects to dashboard if already authenticated
 */
const PublicRoute: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  
  if (isLoading) {
    return (
      <div className="loading-screen">
        <Loader2 className="spin" size={48} />
        <p>Loading...</p>
      </div>
    );
  }
  
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }
  
  return <Outlet />;
};

/**
 * Main App Router
 */
const AppRouter: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public routes - redirect to dashboard if logged in */}
        <Route element={<PublicRoute />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
        </Route>

        {/* Admin routes - require ADMIN role */}
        <Route element={<AdminRoute />}>
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<AdminDashboard />} />
            <Route path="users" element={<AdminUsers />} />
            <Route path="jobs" element={<AdminJobs />} />
            <Route path="panels" element={<AdminPanels />} />
            <Route path="models" element={<AdminModels />} />
            <Route path="tools" element={<AdminTools />} />
            <Route path="invite-codes" element={<AdminInviteCodes />} />
          </Route>
        </Route>
        
        {/* Protected routes - require authentication */}
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<App />} />
          <Route path="/guide/:section" element={<App />} />
          <Route path="/:tab" element={<App />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
};

export default AppRouter;
