/**
 * Admin Layout
 * Separate layout with its own sidebar for admin pages.
 * Does NOT show the teacher sidebar/tabs.
 */
import React, { useState, useEffect } from 'react';
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Users,
  Activity,
  ArrowLeft,
  ShieldCheck,
  PanelTop,
  Cpu,
  Wrench,
  Ticket,
  Menu,
  X,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import './Admin.css';

const ADMIN_NAV = [
  { to: '/admin', icon: LayoutDashboard, label: 'Dashboard', end: true },
  { to: '/admin/users', icon: Users, label: 'Quản lý Users' },
  { to: '/admin/jobs', icon: Activity, label: 'Quản lý Jobs' },
  { to: '/admin/panels', icon: PanelTop, label: 'Quản lý Panel' },
  { to: '/admin/models', icon: Cpu, label: 'Quản lý Model' },
  { to: '/admin/tools', icon: Wrench, label: 'Quản lý Tools' },
  { to: '/admin/invite-codes', icon: Ticket, label: 'Quản lý Mã mời' },
];

const AdminLayout: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close sidebar on route change (mobile)
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  // Close sidebar on resize to desktop
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 769px)');
    const handler = () => { if (mq.matches) setMobileOpen(false); };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  // Prevent body scroll when mobile sidebar is open
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [mobileOpen]);

  return (
    <div className="admin-app">
      {/* Mobile top bar */}
      <div className="admin-mobile-topbar">
        <button
          className="mobile-hamburger"
          onClick={() => setMobileOpen(true)}
          aria-label="Mở menu"
        >
          <Menu size={22} />
        </button>
        <span className="admin-mobile-topbar-title">Admin Panel</span>
        <div className="mobile-topbar-spacer" />
      </div>

      {/* Overlay for mobile */}
      {mobileOpen && (
        <div
          className="sidebar-overlay"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Admin Sidebar */}
      <aside className={`admin-sidebar ${mobileOpen ? 'admin-sidebar-open' : ''}`}>
        <div className="admin-sidebar-header">
          <ShieldCheck size={28} />
          <div>
            <h1>Admin Panel</h1>
            <span className="admin-badge">Administrator</span>
          </div>
          <button
            className="sidebar-close-btn"
            onClick={() => setMobileOpen(false)}
            aria-label="Đóng menu"
          >
            <X size={20} />
          </button>
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
