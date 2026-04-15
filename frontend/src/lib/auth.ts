/**
 * Authentication utilities for frontend.
 * Primary: httpOnly cookie set by server.
 * Fallback: Bearer token stored in sessionStorage for cross-origin cookie restrictions
 * (e.g. Safari ITP, Chrome third-party cookie blocking).
 * sessionStorage is cleared automatically when the browser tab/session closes.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';
const SESSION_TOKEN_KEY = 'session_token';

export interface User {
  username: string;
  is_owner: boolean;
}

export interface LoginData {
  username: string;
  password: string;
}

export interface AuthResponse {
  success: boolean;
  message: string;
  user?: User;
}

export interface AuthStatus {
  authenticated: boolean;
  user?: User;
}

function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return sessionStorage.getItem(SESSION_TOKEN_KEY);
}

function setStoredToken(token: string): void {
  if (typeof window !== 'undefined') {
    sessionStorage.setItem(SESSION_TOKEN_KEY, token);
  }
}

function clearStoredToken(): void {
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem(SESSION_TOKEN_KEY);
    // Also clear legacy localStorage token if present
    localStorage.removeItem('auth_token');
  }
}

export function getAuthHeaders(): HeadersInit {
  const token = getStoredToken();
  if (token) {
    return { 'Authorization': `Bearer ${token}` };
  }
  return {};
}

export async function login(credentials: LoginData): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(credentials),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Login failed');
  }

  const data = await response.json();

  // Store token for Bearer fallback when cross-origin cookies are blocked
  if (data.token) {
    setStoredToken(data.token);
  }

  return { success: data.success, message: data.message, user: data.user };
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
    headers: getAuthHeaders(),
  });
  clearStoredToken();
}

export async function getCurrentUser(): Promise<User> {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    credentials: 'include',
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error('Not authenticated');
  }

  const data = await response.json();
  return data.user;
}

export async function checkAuthStatus(): Promise<AuthStatus> {
  try {
    const user = await getCurrentUser();
    return { authenticated: true, user };
  } catch {
    return { authenticated: false };
  }
}
