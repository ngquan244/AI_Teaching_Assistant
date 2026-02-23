/**
 * Admin User Management Page
 * List, edit, and manage users
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Search,
  Edit3,
  Trash2,
  KeyRound,
  Loader2,
  AlertCircle,
  Check,
  Users,
} from 'lucide-react';
import {
  adminApi,
  type AdminUser,
  type AdminUserList,
  type UpdateUserRequest,
} from '../../api/admin';
import { useAuth } from '../../context/AuthContext';
import './Admin.css';

const AdminUsers: React.FC = () => {
  const { user: currentUser } = useAuth();
  const [data, setData] = useState<AdminUserList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Filters
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  // Modal
  const [editUser, setEditUser] = useState<AdminUser | null>(null);
  const [editForm, setEditForm] = useState<UpdateUserRequest>({});
  const [resetUser, setResetUser] = useState<AdminUser | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [deleteUser, setDeleteUser] = useState<AdminUser | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await adminApi.listUsers({
        page,
        page_size: 20,
        role: roleFilter || undefined,
        status: statusFilter || undefined,
        search: search || undefined,
      });
      setData(result);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, [page, search, roleFilter, statusFilter]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  // Debounced search
  const [searchInput, setSearchInput] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 400);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Auto-dismiss success
  useEffect(() => {
    if (success) {
      const t = setTimeout(() => setSuccess(null), 3000);
      return () => clearTimeout(t);
    }
  }, [success]);

  // --- Edit User ---
  const openEdit = (user: AdminUser) => {
    setEditUser(user);
    setEditForm({ name: user.name, role: user.role, status: user.status });
  };

  const handleEdit = async () => {
    if (!editUser) return;
    try {
      setActionLoading(true);
      await adminApi.updateUser(editUser.id, editForm);
      setSuccess(`User ${editUser.email} updated`);
      setEditUser(null);
      fetchUsers();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Update failed');
    } finally {
      setActionLoading(false);
    }
  };

  // --- Reset Password ---
  const handleResetPassword = async () => {
    if (!resetUser) return;
    try {
      setActionLoading(true);
      await adminApi.resetUserPassword(resetUser.id, { new_password: newPassword });
      setSuccess(`Password reset for ${resetUser.email}`);
      setResetUser(null);
      setNewPassword('');
    } catch (err: any) {
      setError(err.response?.data?.error || 'Reset failed');
    } finally {
      setActionLoading(false);
    }
  };

  // --- Delete User ---
  const handleDelete = async () => {
    if (!deleteUser) return;
    try {
      setActionLoading(true);
      await adminApi.deleteUser(deleteUser.id);
      setSuccess(`User ${deleteUser.email} deleted`);
      setDeleteUser(null);
      fetchUsers();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Delete failed');
    } finally {
      setActionLoading(false);
    }
  };

  const formatDate = (d: string | null) => {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('vi-VN', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="admin-dashboard">
      <h1 className="admin-page-title">Quản lý Users</h1>
      <p className="admin-page-subtitle">
        Xem, chỉnh sửa quyền và trạng thái tài khoản người dùng
      </p>

      {error && (
        <div className="admin-error">
          <AlertCircle size={16} /> {error}
        </div>
      )}
      {success && <div className="admin-success">{success}</div>}

      {/* Filters */}
      <div className="admin-table-header">
        <div className="admin-filters">
          <div style={{ position: 'relative' }}>
            <Search
              size={16}
              style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}
            />
            <input
              className="admin-filter-input"
              placeholder="Tìm theo email hoặc tên..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              style={{ paddingLeft: '2rem' }}
            />
          </div>
          <select
            className="admin-filter-select"
            value={roleFilter}
            onChange={(e) => { setRoleFilter(e.target.value); setPage(1); }}
          >
            <option value="">Tất cả Role</option>
            <option value="ADMIN">Admin</option>
            <option value="TEACHER">Teacher</option>
          </select>
          <select
            className="admin-filter-select"
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          >
            <option value="">Tất cả Status</option>
            <option value="ACTIVE">Active</option>
            <option value="DISABLED">Disabled</option>
            <option value="PENDING">Pending</option>
          </select>
        </div>
        {data && (
          <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
            {data.total} users
          </span>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <div className="admin-loading">
          <Loader2 className="spin" size={28} />
        </div>
      ) : !data || data.items.length === 0 ? (
        <div className="admin-empty">
          <Users size={40} style={{ marginBottom: '0.5rem', opacity: 0.4 }} />
          <p>Không tìm thấy user nào</p>
        </div>
      ) : (
        <>
          <div className="admin-table-wrapper">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Đăng ký</th>
                  <th>Login cuối</th>
                  <th>Hành động</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <div>
                        <strong>{u.name}</strong>
                        {u.id === currentUser?.id && (
                          <span style={{ color: 'var(--primary-light)', fontSize: '0.72rem', marginLeft: 6 }}>
                            (bạn)
                          </span>
                        )}
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                          {u.email}
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className={`admin-badge-role ${u.role.toLowerCase()}`}>
                        {u.role}
                      </span>
                    </td>
                    <td>
                      <span className={`admin-badge-status ${u.status.toLowerCase()}`}>
                        {u.status}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      {formatDate(u.created_at)}
                    </td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      {formatDate(u.last_login_at)}
                    </td>
                    <td>
                      <div className="admin-actions">
                        <button
                          className="admin-action-btn"
                          title="Chỉnh sửa"
                          onClick={() => openEdit(u)}
                        >
                          <Edit3 size={15} />
                        </button>
                        <button
                          className="admin-action-btn"
                          title="Reset password"
                          onClick={() => { setResetUser(u); setNewPassword(''); }}
                        >
                          <KeyRound size={15} />
                        </button>
                        {u.id !== currentUser?.id && (
                          <button
                            className="admin-action-btn danger"
                            title="Xóa"
                            onClick={() => setDeleteUser(u)}
                          >
                            <Trash2 size={15} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {data.pages > 1 && (
            <div className="admin-pagination">
              <span>
                Trang {data.page} / {data.pages}
              </span>
              <div className="admin-pagination-btns">
                <button
                  className="admin-pagination-btn"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Trước
                </button>
                <button
                  className="admin-pagination-btn"
                  disabled={page >= data.pages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Sau
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Edit Modal */}
      {editUser && (
        <div className="admin-modal-overlay" onClick={() => setEditUser(null)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Chỉnh sửa User</h3>
            <div className="admin-modal-field">
              <label>Tên</label>
              <input
                value={editForm.name || ''}
                onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="admin-modal-field">
              <label>Role</label>
              <select
                value={editForm.role || ''}
                onChange={(e) => setEditForm((f) => ({ ...f, role: e.target.value as any }))}
              >
                <option value="TEACHER">Teacher</option>
                <option value="ADMIN">Admin</option>
              </select>
            </div>
            <div className="admin-modal-field">
              <label>Status</label>
              <select
                value={editForm.status || ''}
                onChange={(e) => setEditForm((f) => ({ ...f, status: e.target.value as any }))}
              >
                <option value="ACTIVE">Active</option>
                <option value="DISABLED">Disabled</option>
                <option value="PENDING">Pending</option>
              </select>
            </div>
            <div className="admin-modal-actions">
              <button className="admin-btn admin-btn-secondary" onClick={() => setEditUser(null)}>
                Hủy
              </button>
              <button
                className="admin-btn admin-btn-primary"
                onClick={handleEdit}
                disabled={actionLoading}
              >
                {actionLoading ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
                {' '}Lưu
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reset Password Modal */}
      {resetUser && (
        <div className="admin-modal-overlay" onClick={() => setResetUser(null)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Reset Password</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
              Đặt mật khẩu mới cho <strong>{resetUser.email}</strong>
            </p>
            <div className="admin-modal-field">
              <label>Mật khẩu mới</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Tối thiểu 8 ký tự"
              />
            </div>
            <div className="admin-modal-actions">
              <button className="admin-btn admin-btn-secondary" onClick={() => setResetUser(null)}>
                Hủy
              </button>
              <button
                className="admin-btn admin-btn-primary"
                onClick={handleResetPassword}
                disabled={actionLoading || newPassword.length < 8}
              >
                {actionLoading ? <Loader2 className="spin" size={16} /> : <KeyRound size={16} />}
                {' '}Reset
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteUser && (
        <div className="admin-modal-overlay" onClick={() => setDeleteUser(null)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Xóa User</h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
              Bạn chắc chắn muốn xóa user <strong>{deleteUser.email}</strong>?
            </p>
            <p style={{ fontSize: '0.8rem', color: 'var(--danger)' }}>
              Hành động này không thể hoàn tác. Tất cả dữ liệu liên quan sẽ bị xóa.
            </p>
            <div className="admin-modal-actions">
              <button className="admin-btn admin-btn-secondary" onClick={() => setDeleteUser(null)}>
                Hủy
              </button>
              <button
                className="admin-btn admin-btn-danger"
                onClick={handleDelete}
                disabled={actionLoading}
              >
                {actionLoading ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
                {' '}Xóa
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminUsers;
