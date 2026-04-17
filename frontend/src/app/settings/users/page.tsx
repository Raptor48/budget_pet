"use client";

import { useAuth } from '@/contexts/auth-context';
import { UsersManagement } from '@/components/settings/users-management';
import { DollarSign } from 'lucide-react';

export default function UsersPage() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <DollarSign className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  // Render for everyone — owner gets full management UI, non-owner gets
  // a read-only list of family members. Access-control for the mutating
  // API routes stays on the backend (owner-only).
  return <UsersManagement readOnly={!user?.is_owner} />;
}
