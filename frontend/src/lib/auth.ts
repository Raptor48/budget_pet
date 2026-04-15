/**
 * Authentication utilities for frontend.
 * Auth state is managed exclusively via httpOnly cookies set by the server.
 * No tokens are stored in localStorage or sessionStorage.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

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

  return response.json();
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  });
}

export async function getCurrentUser(): Promise<User> {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    credentials: 'include',
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
