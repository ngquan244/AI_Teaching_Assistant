/**
 * Admin Dashboard Page
 * System overview with key statistics
 */
import React, { useEffect, useState } from 'react';
import {
  Users,
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  TrendingUp,
  UserPlus,
  Zap,
  Loader2,
  AlertCircle,
  BarChart3,
} from 'lucide-react';
import { adminApi, type DashboardStats } from '../../api/admin';
import './Admin.css';

const AdminDashboard: React.FC = () => {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await adminApi.getDashboardStats();
      setStats(data);
    } catch (err: any) {
      setError(err.response?.data?.error || err.message || 'Failed to load stats');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
  }, []);

  if (loading) {
    return (
      <div className="admin-loading">
        <Loader2 className="spin" size={36} />
        <p>Loading dashboard...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="admin-dashboard">
        <div className="admin-error">
          <AlertCircle size={18} />
          {error}
        </div>
      </div>
    );
  }

  if (!stats) return null;

  return (
    <div className="admin-dashboard">
      <h1 className="admin-page-title">Dashboard</h1>
      <p className="admin-page-subtitle">
        Tổng quan hệ thống Teaching Assistant Grader
      </p>

      {/* User Stats */}
      <div className="admin-stats-grid">
        <div className="admin-stat-card">
          <div className="admin-stat-icon blue">
            <Users size={22} />
          </div>
          <div className="admin-stat-info">
            <h3>{stats.users.total}</h3>
            <p>Tổng Users</p>
            <div className="stat-sub">
              {stats.users.active} active · {stats.users.disabled} disabled
            </div>
          </div>
        </div>

        <div className="admin-stat-card">
          <div className="admin-stat-icon green">
            <UserPlus size={22} />
          </div>
          <div className="admin-stat-info">
            <h3>{stats.users.new_7d}</h3>
            <p>Users mới (7 ngày)</p>
            <div className="stat-sub">+{stats.users.new_24h} trong 24h</div>
          </div>
        </div>

        <div className="admin-stat-card">
          <div className="admin-stat-icon purple">
            <Activity size={22} />
          </div>
          <div className="admin-stat-info">
            <h3>{stats.jobs.total}</h3>
            <p>Tổng Jobs</p>
            <div className="stat-sub">{stats.jobs.last_24h} trong 24h qua</div>
          </div>
        </div>

        <div className="admin-stat-card">
          <div className="admin-stat-icon amber">
            <Clock size={22} />
          </div>
          <div className="admin-stat-info">
            <h3>{stats.jobs.running}</h3>
            <p>Đang chạy</p>
            <div className="stat-sub">Queued + Started + Progress</div>
          </div>
        </div>

        <div className="admin-stat-card">
          <div className="admin-stat-icon green">
            <CheckCircle2 size={22} />
          </div>
          <div className="admin-stat-info">
            <h3>{stats.jobs.succeeded}</h3>
            <p>Thành công</p>
            <div className="stat-sub">{stats.jobs.success_rate}% success rate</div>
          </div>
        </div>

        <div className="admin-stat-card">
          <div className="admin-stat-icon red">
            <XCircle size={22} />
          </div>
          <div className="admin-stat-info">
            <h3>{stats.jobs.failed}</h3>
            <p>Thất bại</p>
            <div className="stat-sub">Cần kiểm tra</div>
          </div>
        </div>
      </div>

      {/* Job Type Distribution */}
      {Object.keys(stats.jobs.type_distribution).length > 0 && (
        <div className="admin-section">
          <h2 className="admin-section-title">
            <BarChart3 size={20} />
            Phân bổ loại Job
          </h2>
          <div className="admin-job-type-grid">
            {Object.entries(stats.jobs.type_distribution)
              .sort(([, a], [, b]) => b - a)
              .map(([type, count]) => (
                <div key={type} className="admin-job-type-item">
                  <span className="type-name">{type}</span>
                  <span className="type-count">{count}</span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Canvas Token Stats */}
      <div className="admin-section">
        <h2 className="admin-section-title">
          <Zap size={20} />
          Canvas Tokens
        </h2>
        <div className="admin-stats-grid" style={{ marginBottom: 0 }}>
          <div className="admin-stat-card">
            <div className="admin-stat-icon cyan">
              <TrendingUp size={22} />
            </div>
            <div className="admin-stat-info">
              <h3>{stats.canvas_tokens.active}</h3>
              <p>Active Tokens</p>
              <div className="stat-sub">
                {stats.canvas_tokens.total} tổng (bao gồm đã revoked)
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminDashboard;
