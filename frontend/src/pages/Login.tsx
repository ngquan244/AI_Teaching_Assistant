/**
 * Login Page
 * Email + Password authentication form with polished UX
 */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Loader2, Mail, Lock, AlertCircle, GraduationCap, Eye, EyeOff, LogIn, ArrowRight } from 'lucide-react';
import type { AxiosError } from 'axios';
import './Auth.css';

interface FormData {
  email: string;
  password: string;
}

interface FormErrors {
  email?: string;
  password?: string;
  general?: string;
}

const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const { login, isLoading } = useAuth();
  const emailInputRef = useRef<HTMLInputElement>(null);
  
  const [formData, setFormData] = useState<FormData>({
    email: '',
    password: '',
  });
  
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [shakeError, setShakeError] = useState(false);
  const [hasEntered, setHasEntered] = useState(false);

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

  // Auto-focus email on mount
  useEffect(() => {
    emailInputRef.current?.focus();
  }, []);

  /**
   * Map backend error messages to user-friendly text
   */
  const humanizeError = (raw: string): string => {
    const lower = raw.toLowerCase();
    if (lower.includes('invalid credentials') || lower.includes('incorrect')) {
      return 'Email or password is incorrect. Please try again.';
    }
    if (lower.includes('locked') || lower.includes('rate limit') || lower.includes('too many')) {
      return 'Too many failed attempts. Please wait a few minutes before trying again.';
    }
    if (lower.includes('disabled') || lower.includes('suspended')) {
      return 'Your account has been disabled. Please contact support.';
    }
    if (lower.includes('not found')) {
      return 'No account found with this email. Would you like to sign up?';
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
    
    if (!formData.password) {
      newErrors.password = 'Please enter your password';
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
    // Clear general error when user starts fixing
    if (errors.general) {
      setErrors(prev => ({ ...prev, general: undefined }));
    }
  };

  /**
   * Trigger shake animation on error
   */
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
      await login({
        email: formData.email.trim().toLowerCase(),
        password: formData.password,
      });
      
      navigate('/');
    } catch (error) {
      const axiosError = error as AxiosError;
      const data = axiosError.response?.data as any;

      let errorMessage = 'Something went wrong. Please try again.';

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

  /**
   * Handle Enter key on email field -> focus password
   */
  const handleEmailKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      document.getElementById('password')?.focus();
    }
  };

  const disabled = isLoading || isSubmitting;

  return (
    <div className="auth-container">
      {/* Decorative background elements */}
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
        className={`auth-card ${!hasEntered ? 'auth-card-animate' : ''} ${shakeError ? 'shake' : ''}`}
        onAnimationEnd={(e) => { if (e.animationName === 'card-enter') setHasEntered(true); }}
      >
        {/* Header */}
        <div className="auth-header">
          <div className="auth-logo">
            <GraduationCap size={36} strokeWidth={1.5} />
          </div>
          <h1>Welcome back</h1>
          <p>Sign in to continue to AI Teaching Assistant</p>
        </div>

        {/* General error */}
        {errors.general && (
          <div className="auth-error auth-error-animate" role="alert">
            <AlertCircle size={18} />
            <span>{errors.general}</span>
          </div>
        )}

        {/* Login form */}
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
                onKeyDown={handleEmailKeyDown}
                disabled={disabled}
                autoComplete="email"
                aria-invalid={!!errors.email}
                aria-describedby={errors.email ? 'email-error' : undefined}
              />
            </div>
            {errors.email && <span id="email-error" className="field-error" role="alert">{errors.email}</span>}
          </div>

          {/* Password field */}
          <div className="form-group">
            <div className="form-label-row">
              <label htmlFor="password">Password</label>
            </div>
            <div className={`input-wrapper ${errors.password ? 'error' : ''} ${formData.password ? 'has-value' : ''}`}>
              <Lock size={18} className="input-icon" />
              <input
                id="password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Enter your password"
                value={formData.password}
                onChange={handleChange}
                disabled={disabled}
                autoComplete="current-password"
                aria-invalid={!!errors.password}
                aria-describedby={errors.password ? 'password-error' : undefined}
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
            {errors.password && <span id="password-error" className="field-error" role="alert">{errors.password}</span>}
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
                Signing in...
              </>
            ) : (
              <>
                <LogIn size={18} />
                Sign In
              </>
            )}
          </button>
        </form>

        {/* Divider */}
        <div className="auth-divider">
          <span>New here?</span>
        </div>

        {/* Footer */}
        <div className="auth-footer-action">
          <Link to="/signup" className="auth-secondary-button">
            Create an account
            <ArrowRight size={16} />
          </Link>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
