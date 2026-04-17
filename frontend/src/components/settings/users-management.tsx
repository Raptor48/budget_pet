"use client";

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { usersApi, membersApi, UserPublic } from '@/lib/api';
import { useAuth } from '@/contexts/auth-context';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Separator } from '@/components/ui/separator';
import { Users, Trash2, UserPlus, AlertCircle } from 'lucide-react';

type Props = {
  /** When true, hide owner-only actions (create/delete) and fall back to the
   * public family-members endpoint which every signed-in user can access. */
  readOnly?: boolean;
};

export function UsersManagement({ readOnly = false }: Props) {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();

  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [formError, setFormError] = useState('');

  // Owners use /api/auth/users (full rows with is_owner + created_at). Other
  // family members fall back to /api/auth/members, which exposes just id and
  // username so the page can still render without a 403.
  const ownerQuery = useQuery({
    queryKey: ['users'],
    queryFn: usersApi.list,
    enabled: !readOnly,
  });
  const memberQuery = useQuery({
    queryKey: ['family-members'],
    queryFn: membersApi.list,
    enabled: readOnly,
  });

  const users: UserPublic[] = readOnly
    ? (memberQuery.data ?? []).map((m) => ({
        id: m.id,
        username: m.username,
        is_owner: false,
        created_at: '',
      }))
    : (ownerQuery.data ?? []);
  const isLoading = readOnly ? memberQuery.isLoading : ownerQuery.isLoading;
  const error = readOnly ? memberQuery.error : ownerQuery.error;

  const createMutation = useMutation({
    mutationFn: usersApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setNewUsername('');
      setNewPassword('');
      setFormError('');
    },
    onError: (err: Error) => {
      setFormError(err.message || 'Failed to create user');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: usersApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    if (newPassword.length < 6) {
      setFormError('Password must be at least 6 characters');
      return;
    }
    createMutation.mutate({ username: newUsername, password: newPassword });
  };

  const canDelete = (u: UserPublic) => {
    if (readOnly) return false;
    if (u.username === currentUser?.username) return false;
    if (u.is_owner && users.filter((x) => x.is_owner).length <= 1) return false;
    return true;
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Users</h1>
        <p className="text-muted-foreground">
          Manage family member accounts
        </p>
      </div>

      {/* Current users */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            Family Members
          </CardTitle>
          <CardDescription>
            All accounts with access to this app
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <p className="text-sm text-muted-foreground">Loading...</p>
          )}
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>Failed to load users</AlertDescription>
            </Alert>
          )}
          {!isLoading && users.length > 0 && (
            <div className="space-y-2">
              {users.map((u) => (
                <div
                  key={u.id}
                  className="flex items-center justify-between rounded-lg border px-4 py-3"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 bg-primary rounded-full flex items-center justify-center">
                      <span className="text-primary-foreground font-semibold text-sm">
                        {u.username.charAt(0).toUpperCase()}
                      </span>
                    </div>
                    <div>
                      <p className="text-sm font-medium">
                        {u.username}
                        {u.username === currentUser?.username && (
                          <span className="ml-2 text-xs text-muted-foreground">(you)</span>
                        )}
                      </p>
                      {u.created_at ? (
                        <p className="text-xs text-muted-foreground">
                          Joined {new Date(u.created_at).toLocaleDateString()}
                        </p>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {u.is_owner && (
                      <Badge variant="secondary">Owner</Badge>
                    )}
                    {canDelete(u) && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive hover:text-destructive"
                        onClick={() => deleteMutation.mutate(u.id)}
                        disabled={deleteMutation.isPending}
                        title="Remove user"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {readOnly ? null : <Separator />}

      {/* Add new user — owner only */}
      {readOnly ? null : (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserPlus className="h-5 w-5" />
            Add Family Member
          </CardTitle>
          <CardDescription>
            Create an account and share the credentials
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleCreate} className="space-y-4 max-w-sm">
            {formError && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}
            {createMutation.isSuccess && (
              <Alert>
                <AlertDescription>
                  User <strong>{users[users.length - 1]?.username}</strong> created successfully.
                  Share the credentials with them.
                </AlertDescription>
              </Alert>
            )}
            <div className="space-y-2">
              <Label htmlFor="new-username">Username</Label>
              <Input
                id="new-username"
                type="text"
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value)}
                placeholder="e.g. anna"
                required
                minLength={2}
                maxLength={50}
                pattern="[a-zA-Z0-9_\-]+"
                title="Letters, numbers, underscores and hyphens only"
                disabled={createMutation.isPending}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-password">Password</Label>
              <Input
                id="new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="At least 6 characters"
                required
                minLength={6}
                disabled={createMutation.isPending}
              />
            </div>
            <Button
              type="submit"
              disabled={createMutation.isPending || !newUsername || !newPassword}
            >
              {createMutation.isPending ? 'Creating...' : 'Create Account'}
            </Button>
          </form>
        </CardContent>
      </Card>
      )}
    </div>
  );
}
