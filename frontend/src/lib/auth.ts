/**
 * Authentication utilities for frontend
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

export interface User {
  username: string;
  logged_in_at: string;
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

/**
 * Login with username and password
 */
export async function login(credentials: LoginData): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include', // Include cookies
    body: JSON.stringify(credentials),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Login failed');
  }

  return response.json();
}

/**
 * Logout current user
 */
export async function logout(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!response.ok) {
    console.warn('Logout request failed, but continuing...');
  }
}

/**
 * Get current user info
 */
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

/**
 * Check authentication status
 */
export async function checkAuthStatus(): Promise<AuthStatus> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/auth/status`, {
      credentials: 'include',
    });

    if (!response.ok) {
      return { authenticated: false };
    }

    const data = await response.json();
    
    if (data.authenticated) {
      // Get user info if authenticated
      try {
        const user = await getCurrentUser();
        return { authenticated: true, user };
      } catch {
        return { authenticated: false };
      }
    }

    return { authenticated: false };
  } catch (error) {
    console.error('Auth status check failed:', error);
    return { authenticated: false };
  }
}
