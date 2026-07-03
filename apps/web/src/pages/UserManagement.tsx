import { useEffect, useState } from 'react';
import { ShieldCheck, AlertCircle, XCircle } from 'lucide-react';
import { listUsers, updateUser } from '../api/client';
import type { User } from '../api/types';
import { useAuth } from '../contexts/AuthContext';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { formatDate } from '../lib/utils';

export function UserManagement() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    listUsers()
      .then(setUsers)
      .catch(() => setError('Failed to load users'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const toggle = async (target: User, field: 'is_active' | 'is_admin') => {
    setSavingId(target.id);
    setError(null);
    try {
      await updateUser(target.id, { [field]: !target[field] });
      load();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to update user');
    } finally {
      setSavingId(null);
    }
  };

  const activeCount = users.filter((u) => u.is_active).length;
  const adminCount = users.filter((u) => u.is_admin).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <ShieldCheck className="h-6 w-6 text-primary" />
          User Management
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Admin-only — activate, deactivate, and grant admin access to accounts
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
          <button type="button" title="Dismiss error" aria-label="Dismiss error" className="ml-auto text-destructive/80 hover:text-destructive" onClick={() => setError(null)}>
            <XCircle className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Users</p>
            <p className="text-xl font-bold mt-1">{users.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Active</p>
            <p className="text-xl font-bold mt-1 text-income">{activeCount}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Admins</p>
            <p className="text-xl font-bold mt-1 text-brand-accent">{adminCount}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">All Accounts</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-muted-foreground py-4 text-center">Loading…</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[640px]">
                <thead>
                  <tr className="text-muted-foreground border-b text-left">
                    <th className="py-2 pr-3 font-medium">Email</th>
                    <th className="py-2 pr-3 font-medium">Name</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium">Role</th>
                    <th className="py-2 pr-3 font-medium">Joined</th>
                    <th className="py-2 pr-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {users.map((u) => {
                    const isSelf = currentUser?.id === u.id;
                    return (
                      <tr key={u.id}>
                        <td className="py-2.5 pr-3">{u.email}</td>
                        <td className="py-2.5 pr-3">{u.full_name || '—'}</td>
                        <td className="py-2.5 pr-3">
                          <Badge variant={u.is_active ? 'income' : 'expense'}>
                            {u.is_active ? 'Active' : 'Inactive'}
                          </Badge>
                        </td>
                        <td className="py-2.5 pr-3">
                          <Badge variant={u.is_admin ? 'default' : 'outline'}>
                            {u.is_admin ? 'Admin' : 'Member'}
                          </Badge>
                        </td>
                        <td className="py-2.5 pr-3 text-muted-foreground">{formatDate(u.created_at)}</td>
                        <td className="py-2.5 pr-3">
                          <div className="flex justify-end gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={isSelf || savingId === u.id}
                              title={isSelf ? "You can't change your own status" : undefined}
                              onClick={() => toggle(u, 'is_active')}
                            >
                              {u.is_active ? 'Deactivate' : 'Activate'}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={isSelf || savingId === u.id}
                              title={isSelf ? "You can't change your own role" : undefined}
                              onClick={() => toggle(u, 'is_admin')}
                            >
                              {u.is_admin ? 'Remove Admin' : 'Make Admin'}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
