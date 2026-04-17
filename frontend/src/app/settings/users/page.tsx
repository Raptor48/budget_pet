"use client";

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/auth-context';
import { UsersManagement } from '@/components/settings/users-management';
import { DollarSign } from 'lucide-react';

export default function UsersPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user && !user.is_owner) {
      router.replace('/settings');
    }
  }, [user, loading, router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <DollarSign className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (!user?.is_owner) {
    return null;
  }

  return <UsersManagement />;
}
