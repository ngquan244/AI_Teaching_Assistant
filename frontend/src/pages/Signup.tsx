/**
 * Signup Page
 * User registration form with Canvas token support
 */
import React, { useState, useRef, useEffect, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getSignupStatus } from '../api/auth';
import { Loader2, Mail, Lock, User, Key, AlertCircle, GraduationCap, Eye, EyeOff, CheckCircle, UserPlus, ArrowRight, ShieldCheck } from 'lucide-react';
import type { AxiosError } from 'axios';
import './Auth.css';

interface FormData {
  email: string;
  name: string;
  password: string;
  confirmPassword: string;
  inviteCode: string;
  canvasAccessToken: string;
}

interface FormErrors {
  email?: string;
  name?: string;
  password?: string;
  confirmPassword?: string;
  inviteCode?: string;
  canvasAccessToken?: string;
  general?: string;
}

const SignupPage: React.FC = () => {
  const navigate = useNavigate();
  const { signup, isLoading } = useAuth();
  const emailInputRef = useRef<HTMLInputElement>(null);
  
  const [formData, setFormData] = useState<FormData>({
    email: '',
    name: '',
    password: '',
    confirmPassword: '',
    inviteCode: '',
    canvasAccessToken: '',
  });
  
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [shakeError, setShakeError] = useState(false);
  const [hasEntered, setHasEntered] = useState(false);
  const [signupMode, setSignupMode] = useState<'open' | 'invite' | 'closed'>('open');
  const [modeLoading, setModeLoading] = useState(true);

  // Memoize star positions so they don't respawn on every re-render
  const stars = useMemo(
    () =>
      Array.from({ length: 20 }, () => ({
        top: `${Math.random() * 100}%`,
        left: `${Math.random() * 100}%`,
        '--duration': `${3 + Math.random() * 4}s`,
        '--delay': `${Math.random() * 5}s`,
      } as React.CSSProperties)),
    [],
  );

  useEffect(() => {
    emailInputRef.current?.focus();
  }, []);

  // Fetch signup mode on mount
  useEffect(() => {
    getSignupStatus()
      .then((res) => setSignupMode(res.mode))
      .catch(() => setSignupMode('open'))  // fallback
      .finally(() => setModeLoading(false));
  }, []);

  /**
   * Password strength indicators
   */
  const passwordChecks = {
    length: formData.password.length >= 8,
    uppercase: /[A-Z]/.test(formData.password),
    lowercase: /[a-z]/.test(formData.password),
    number: /[0-9]/.test(formData.password),
    special: /[!@#$%^&*()_+\-=\[\]{}|;':,.<>?/`~"\\]/.test(formData.password),
  };

  const passwordStrength = Object.values(passwordChecks).filter(Boolean).length;

  const strengthLabel = passwordStrength <= 1 ? 'weak' : passwordStrength <= 2 ? 'fair' : passwordStrength <= 3 ? 'good' : 'strong';

  /**
   * Map backend error messages to user-friendly text
   */
  const humanizeError = (raw: string): string => {
    const lower = raw.toLowerCase();
    if (lower.includes('already exists') || lower.includes('already registered') || lower.includes('duplicate')) {
      return 'An account with this email already exists. Try signing in instead.';
    }
    if (lower.includes('too common')) {
      return 'This password is too common. Please choose a more unique password.';
    }
    return raw;
  };

  /**
   * Validate form fields
   */
  const validate = (): boolean => {
    const newErrors: FormErrors = {};
    
    if (!formData.email.trim()) {
      newErrors.email = 'Please enter your email address';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) {
      newErrors.email = 'This doesn\'t look like a valid email';
    }
    
    if (!formData.name.trim()) {
      newErrors.name = 'Please enter your name';
    } else if (formData.name.trim().length < 2) {
      newErrors.name = 'Name must be at least 2 characters';
    }
    
    if (!formData.password) {
      newErrors.password = 'Please create a password';
    } else if (passwordStrength < 5) {
      newErrors.password = 'Please meet all password requirements below';
    }
    
    if (!formData.confirmPassword) {
      newErrors.confirmPassword = 'Please confirm your password';
    } else if (formData.password !== formData.confirmPassword) {
      newErrors.confirmPassword = 'Passwords do not match';
    }

    if (signupMode === 'invite' && !formData.inviteCode.trim()) {
      newErrors.inviteCode = 'Vui lòng nhập mã mời';
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  /**
   * Handle input changes
   */
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    if (errors[name as keyof FormErrors]) {
      setErrors(prev => ({ ...prev, [name]: undefined }));
    }
    if (errors.general) {
      setErrors(prev => ({ ...prev, general: undefined }));
    }
  };

  const triggerShake = () => {
    setShakeError(true);
    setTimeout(() => setShakeError(false), 600);
  };

  /**
   * Handle form submission
   */
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!validate()) {
      triggerShake();
      return;
    }
    
    setIsSubmitting(true);
    setErrors({});
    
    try {
      await signup({
        email: formData.email.trim().toLowerCase(),
        name: formData.name.trim(),
        password: formData.password,
        invite_code: formData.inviteCode.trim() || undefined,
        canvas_access_token: formData.canvasAccessToken.trim() || undefined,
      });
      
      navigate('/');
    } catch (error) {
      const axiosError = error as AxiosError;
      const data = axiosError.response?.data as any;

      let errorMessage = 'Registration failed. Please try again.';

      if (data?.detail && Array.isArray(data.detail)) {
        const messages = data.detail.map((err: any) => {
          const msg = (err.msg || '').replace(/^Value error, /i, '');
          return msg;
        });
        errorMessage = messages.join('. ');
      } else if (data?.detail && typeof data.detail === 'string') {
        errorMessage = data.detail;
      } else if (data?.error) {
        errorMessage = data.error;
      }

      setErrors({ general: humanizeError(errorMessage) });
      triggerShake();
    } finally {
      setIsSubmitting(false);
    }
  };

  const disabled = isLoading || isSubmitting;

  // ── Loading signup mode ────────────────────────────────────────────
  if (modeLoading) {
    return (
      <div className="auth-container">
        <div className="auth-card" style={{ textAlign: 'center', padding: '3rem' }}>
          <Loader2 size={32} className="spin" />
        </div>
      </div>
    );
  }

  // ── Signup is closed ───────────────────────────────────────────────
  if (signupMode === 'closed') {
    return (
      <div className="auth-container">
        <div className="auth-bg-decoration">
          <div className="auth-bg-circle auth-bg-circle-1" />
          <div className="auth-bg-circle auth-bg-circle-2" />
          <div className="auth-bg-circle auth-bg-circle-3" />
        </div>
        <div className="auth-card">
          <div className="auth-header">
            <div className="auth-logo">
              <GraduationCap size={36} strokeWidth={1.5} />
            </div>
            <h1>Đăng ký tạm tắt</h1>
            <p>Hiện tại hệ thống không mở đăng ký. Vui lòng liên hệ quản trị viên để được cấp tài khoản.</p>
          </div>
          <div className="auth-footer-action">
            <Link to="/login" className="auth-secondary-button">
              Đăng nhập
              <ArrowRight size={16} />
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-container">
      {/* Decorative background */}
      <div className="auth-bg-decoration">
        <div className="auth-bg-circle auth-bg-circle-1" />
        <div className="auth-bg-circle auth-bg-circle-2" />
        <div className="auth-bg-circle auth-bg-circle-3" />
      </div>

      {/* Twinkling stars */}
      <div className="auth-stars">
        {stars.map((star, i) => (
          <div
            key={i}
            className="auth-star"
            style={star}
          />
        ))}
      </div>

      {/* Glowing accent lines */}
      <div className="auth-glow-line auth-glow-line-1" />
      <div className="auth-glow-line auth-glow-line-2" />

      <div
        className={`auth-card auth-card-wide ${!hasEntered ? 'auth-card-animate' : ''} ${shakeError ? 'shake' : ''}`}
        onAnimationEnd={(e) => { if (e.animationName === 'card-enter') setHasEntered(true); }}
      >
        {/* Header */}
        <div className="auth-header">
          <div className="auth-logo">
            <GraduationCap size={36} strokeWidth={1.5} />
          </div>
          <h1>Create your account</h1>
          <p>Get started with AI Teaching Assistant</p>
        </div>

        {/* General error */}
        {errors.general && (
          <div className="auth-error auth-error-animate" role="alert">
            <AlertCircle size={18} />
            <span>{errors.general}</span>
          </div>
        )}

        {/* Signup form */}
        <form onSubmit={handleSubmit} className="auth-form" noValidate>
          {/* Email field */}
          <div className="form-group">
            <label htmlFor="email">Email address</label>
            <div className={`input-wrapper ${errors.email ? 'error' : ''} ${formData.email ? 'has-value' : ''}`}>
              <Mail size={18} className="input-icon" />
              <input
                ref={emailInputRef}
                id="email"
                name="email"
                type="email"
                placeholder="you@example.com"
                value={formData.email}
                onChange={handleChange}
                disabled={disabled}
                autoComplete="email"
                aria-invalid={!!errors.email}
                aria-describedby={errors.email ? 'signup-email-error' : undefined}
              />
            </div>
            {errors.email && <span id="signup-email-error" className="field-error" role="alert">{errors.email}</span>}
          </div>

          {/* Name field */}
          <div className="form-group">
            <label htmlFor="name">Full name</label>
            <div className={`input-wrapper ${errors.name ? 'error' : ''} ${formData.name ? 'has-value' : ''}`}>
              <User size={18} className="input-icon" />
              <input
                id="name"
                name="name"
                type="text"
                placeholder="John Doe"
                value={formData.name}
                onChange={handleChange}
                disabled={disabled}
                autoComplete="name"
                aria-invalid={!!errors.name}
              />
            </div>
            {errors.name && <span className="field-error" role="alert">{errors.name}</span>}
          </div>

          {/* Password field */}
          <div className="form-group">
            <label htmlFor="password">Password</label>
            <div className={`input-wrapper ${errors.password ? 'error' : ''} ${formData.password ? 'has-value' : ''}`}>
              <Lock size={18} className="input-icon" />
              <input
                id="password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Create a strong password"
                value={formData.password}
                onChange={handleChange}
                disabled={disabled}
                autoComplete="new-password"
                aria-invalid={!!errors.password}
              />
              <button
                type="button"
                className="input-action"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex={-1}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                title={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            {errors.password && <span className="field-error" role="alert">{errors.password}</span>}
            
            {/* Password strength bar */}
            {formData.password && (
              <>
                <div className="password-strength-bar">
                  {[1, 2, 3, 4, 5].map(i => (
                    <div
                      key={i}
                      className={`strength-segment ${i <= passwordStrength ? `active strength-${strengthLabel}` : ''}`}
                    />
                  ))}
                </div>
                <div className="password-strength-label">
                  <span className={`strength-${strengthLabel}`}>
                    {strengthLabel === 'weak' ? 'Weak' : strengthLabel === 'fair' ? 'Fair' : strengthLabel === 'good' ? 'Good' : 'Strong'}
                  </span>
                </div>
              </>
            )}

            {/* Password requirements checklist */}
            {formData.password && (
              <div className="password-requirements">
                <div className={`requirement ${passwordChecks.length ? 'met' : ''}`}>
                  <CheckCircle size={14} />
                  <span>8+ characters</span>
                </div>
                <div className={`requirement ${passwordChecks.uppercase ? 'met' : ''}`}>
                  <CheckCircle size={14} />
                  <span>Uppercase letter</span>
                </div>
                <div className={`requirement ${passwordChecks.lowercase ? 'met' : ''}`}>
                  <CheckCircle size={14} />
                  <span>Lowercase letter</span>
                </div>
                <div className={`requirement ${passwordChecks.number ? 'met' : ''}`}>
                  <CheckCircle size={14} />
                  <span>Number</span>
                </div>
                <div className={`requirement ${passwordChecks.special ? 'met' : ''}`}>
                  <CheckCircle size={14} />
                  <span>Special character (!@#$...)</span>
                </div>
              </div>
            )}
          </div>

          {/* Confirm Password field */}
          <div className="form-group">
            <label htmlFor="confirmPassword">Confirm password</label>
            <div className={`input-wrapper ${errors.confirmPassword ? 'error' : ''} ${formData.confirmPassword ? 'has-value' : ''}`}>
              <Lock size={18} className="input-icon" />
              <input
                id="confirmPassword"
                name="confirmPassword"
                type={showPassword ? 'text' : 'password'}
                placeholder="Re-enter your password"
                value={formData.confirmPassword}
                onChange={handleChange}
                disabled={disabled}
                autoComplete="new-password"
                aria-invalid={!!errors.confirmPassword}
              />
            </div>
            {errors.confirmPassword && <span className="field-error" role="alert">{errors.confirmPassword}</span>}
          </div>

          {/* Invite Code field (only when mode=invite) */}
          {signupMode === 'invite' && (
            <div className="form-group">
              <label htmlFor="inviteCode">Mã mời</label>
              <div className={`input-wrapper ${errors.inviteCode ? 'error' : ''} ${formData.inviteCode ? 'has-value' : ''}`}>
                <ShieldCheck size={18} className="input-icon" />
                <input
                  id="inviteCode"
                  name="inviteCode"
                  type="text"
                  placeholder="Nhập mã mời từ quản trị viên"
                  value={formData.inviteCode}
                  onChange={handleChange}
                  disabled={disabled}
                  autoComplete="off"
                  aria-invalid={!!errors.inviteCode}
                />
              </div>
              {errors.inviteCode && <span className="field-error" role="alert">{errors.inviteCode}</span>}
            </div>
          )}

          {/* Canvas Access Token field (optional) */}
          <div className="form-group">
            <label htmlFor="canvasAccessToken">
              Canvas Access Token
              <span className="optional-badge">Optional</span>
            </label>
            <div className={`input-wrapper ${errors.canvasAccessToken ? 'error' : ''} ${formData.canvasAccessToken ? 'has-value' : ''}`}>
              <Key size={18} className="input-icon" />
              <input
                id="canvasAccessToken"
                name="canvasAccessToken"
                type="password"
                placeholder="Paste your Canvas LMS token"
                value={formData.canvasAccessToken}
                onChange={handleChange}
                disabled={disabled}
              />
            </div>
            <span className="field-hint">
              You can add this later from your profile settings.
            </span>
          </div>

          {/* Submit button */}
          <button
            type="submit"
            className="auth-button"
            disabled={disabled}
          >
            {isSubmitting ? (
              <>
                <Loader2 size={18} className="spin" />
                Creating account...
              </>
            ) : (
              <>
                <UserPlus size={18} />
                Create Account
              </>
            )}
          </button>
        </form>

        {/* Divider */}
        <div className="auth-divider">
          <span>Already have an account?</span>
        </div>

        {/* Footer */}
        <div className="auth-footer-action">
          <Link to="/login" className="auth-secondary-button">
            Sign in instead
            <ArrowRight size={16} />
          </Link>
        </div>
      </div>
    </div>
  );
};

export default SignupPage;
