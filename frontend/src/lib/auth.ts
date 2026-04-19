/**
 * Authentication utilities for frontend.
 * Primary: httpOnly cookie set by server (30-day lifetime).
 * Fallback: Bearer token stored in localStorage for cross-origin cookie restrictions
 * (Safari ITP, Chrome third-party cookie blocking, PWAs on iOS where cookies are
 * routinely dropped between app launches).
 * localStorage persists across browser/app restarts, mirroring the 30-day server
 * session — users stay signed in until they log out or the server session expires.
 * A legacy sessionStorage token (from earlier versions) is migrated transparently.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';
const SESSION_TOKEN_KEY = 'session_token';
const LEGACY_LOCAL_KEY = 'auth_token';

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
  // Prefer the persistent localStorage token. Fall back to any lingering
  // sessionStorage token from older builds so signed-in users are not kicked
  // out on upgrade; the token is migrated to localStorage on next write.
  const persistent = localStorage.getItem(SESSION_TOKEN_KEY);
  if (persistent) return persistent;
  try {
    return sessionStorage.getItem(SESSION_TOKEN_KEY);
  } catch {
    return null;
  }
}

function setStoredToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(SESSION_TOKEN_KEY, token);
  try {
    sessionStorage.removeItem(SESSION_TOKEN_KEY);
  } catch {
    // sessionStorage may be unavailable (private mode on some browsers).
  }
}

function clearStoredToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(SESSION_TOKEN_KEY);
  localStorage.removeItem(LEGACY_LOCAL_KEY);
  try {
    sessionStorage.removeItem(SESSION_TOKEN_KEY);
  } catch {
    // Ignore — already unavailable.
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
