"use client";

/**
 * Authentication context for managing global auth state
 */

import React, { createContext, useContext, useEffect, useState } from 'react';
import {
  User,
  AuthStatus,
  checkAuthStatus,
  logout as authLogout,
  loginWithTelegramWebApp,
} from '@/lib/auth';

interface AuthContextType {
  isAuthenticated: boolean;
  user: User | null;
  loading: boolean;
  login: (user: User) => void;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = async () => {
    try {
      // If we're running inside a Telegram Mini App AND aren't already
      // signed in, exchange the signed initData for a session before the
      // regular cookie check. The helper returns null silently on any
      // failure so the manual login flow remains the fallback.
      if (typeof window !== 'undefined') {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const tg = (window as any).Telegram?.WebApp;
        if (tg?.initData) {
          try {
            tg.ready?.();
            tg.expand?.();
          } catch {
            // older Telegram clients may not expose these — ignore.
          }
          const tgLogin = await loginWithTelegramWebApp();
          if (tgLogin?.success && tgLogin.user) {
            setIsAuthenticated(true);
            setUser(tgLogin.user);
            setLoading(false);
            return;
          }
        }
      }

      const status: AuthStatus = await checkAuthStatus();
      setIsAuthenticated(status.authenticated);
      setUser(status.user || null);
    } catch (error) {
      console.error('Auth check failed:', error);
      setIsAuthenticated(false);
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const login = (user: User) => {
    setIsAuthenticated(true);
    setUser(user);
  };

  const logout = async () => {
    try {
      await authLogout();
    } catch (error) {
      console.error('Logout failed:', error);
    } finally {
      setIsAuthenticated(false);
      setUser(null);
      // Redirect to login
      window.location.href = '/login';
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  const value: AuthContextType = {
    isAuthenticated,
    user,
    loading,
    login,
    logout,
    checkAuth,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
