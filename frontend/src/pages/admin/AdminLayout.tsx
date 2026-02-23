/**
 * Admin Layout
 * Separate layout with its own sidebar for admin pages.
 * Does NOT show the teacher sidebar/tabs.
 */
import React from 'react';
import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  Users,
  Activity,
  ArrowLeft,
  ShieldCheck,
  PanelTop,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import './Admin.css';

const ADMIN_NAV = [
  { to: '/admin', icon: LayoutDashboard, label: 'Dashboard', end: true },
  { to: '/admin/users', icon: Users, label: 'Quản lý Users' },
  { to: '/admin/jobs', icon: Activity, label: 'Quản lý Jobs' },
  { to: '/admin/panels', icon: PanelTop, label: 'Quản lý Panel' },
];

const AdminLayout: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="admin-app">
      {/* Admin Sidebar */}
      <aside className="admin-sidebar">
        <div className="admin-sidebar-header">
          <ShieldCheck size={28} />
          <div>
            <h1>Admin Panel</h1>
            <span className="admin-badge">Administrator</span>
          </div>
        </div>

        <nav className="admin-nav">
          {ADMIN_NAV.map(({ to, icon: Icon, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `admin-nav-item ${isActive ? 'active' : ''}`
              }
            >
              <Icon size={20} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="admin-sidebar-footer">
          <button
            className="admin-nav-item admin-back-btn"
            onClick={() => navigate('/')}
          >
            <ArrowLeft size={20} />
            <span>Về Teacher UI</span>
          </button>

          <div className="admin-user-info">
            <div className="admin-avatar">
              {user?.name?.charAt(0).toUpperCase() || 'A'}
            </div>
            <div className="admin-user-text">
              <span className="admin-user-name">{user?.name}</span>
              <span className="admin-user-email">{user?.email}</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Admin Content */}
      <main className="admin-content">
        <Outlet />
      </main>
    </div>
  );
};

export default AdminLayout;
