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
  token?: string;  // Token for Authorization header (Safari compatibility)
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

  const data = await response.json();
  
  // Save token to localStorage for Safari compatibility (when cross-site tracking is enabled)
  if (data.token && typeof window !== 'undefined') {
    localStorage.setItem('auth_token', data.token);
  }

  return data;
}

/**
 * Logout current user
 */
export async function logout(): Promise<void> {
  // Get token for Authorization header
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  
  const headers: HeadersInit = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  
  const response = await fetch(`${API_BASE_URL}/api/auth/logout`, {
    method: 'POST',
    headers,
    credentials: 'include',
  });

  // Remove token from localStorage
  if (typeof window !== 'undefined') {
    localStorage.removeItem('auth_token');
  }

  if (!response.ok) {
    console.warn('Logout request failed, but continuing...');
  }
}

/**
 * Get current user info
 */
export async function getCurrentUser(): Promise<User> {
  // Get token for Authorization header
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
  
  const headers: HeadersInit = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    headers,
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
    // Get token for Authorization header
    const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
    
    const headers: HeadersInit = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    
    const response = await fetch(`${API_BASE_URL}/api/auth/status`, {
      headers,
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
