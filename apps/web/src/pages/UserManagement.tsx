import { useEffect, useState } from 'react';
import { ShieldCheck, AlertCircle, XCircle, Pencil, Check } from 'lucide-react';
import { listUsers, listRoles, updateUser } from '../api/client';
import type { Role, User } from '../api/types';
import { useAuth } from '../contexts/AuthContext';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { formatDate } from '../lib/utils';

export function UserManagement() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [editingNameId, setEditingNameId] = useState<number | null>(null);
  const [nameDraft, setNameDraft] = useState('');

  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([listUsers(), listRoles()])
      .then(([u, r]) => { setUsers(u); setRoles(r); })
      .catch(() => setError('Failed to load users'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const toggleActive = async (target: User) => {
    setSavingId(target.id);
    setError(null);
    try {
      await updateUser(target.id, { is_active: !target.is_active });
      load();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to update user');
    } finally {
      setSavingId(null);
    }
  };

  const changeRole = async (target: User, roleId: string) => {
    setSavingId(target.id);
    setError(null);
    try {
      await updateUser(target.id, { role_id: Number(roleId) });
      load();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to update user');
    } finally {
      setSavingId(null);
    }
  };

  const startEditName = (target: User) => {
    setEditingNameId(target.id);
    setNameDraft(target.full_name || '');
  };

  const cancelEditName = () => {
    setEditingNameId(null);
    setNameDraft('');
  };

  const saveName = async (target: User) => {
    const trimmed = nameDraft.trim();
    if (!trimmed || trimmed === target.full_name) {
      cancelEditName();
      return;
    }
    setSavingId(target.id);
    setError(null);
    try {
      await updateUser(target.id, { full_name: trimmed });
      cancelEditName();
      load();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to update user');
    } finally {
      setSavingId(null);
    }
  };

  const activeCount = users.filter((u) => u.is_active).length;
  const noRoleCount = users.filter((u) => !u.role).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <ShieldCheck className="h-6 w-6 text-primary" />
          User Management
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Activate, deactivate, and assign roles to accounts
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
            <p className="text-xs text-muted-foreground uppercase tracking-wide">No Role Assigned</p>
            <p className="text-xl font-bold mt-1 text-brand-accent">{noRoleCount}</p>
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
                        <td className="py-2.5 pr-3">
                          {editingNameId === u.id ? (
                            <div className="flex items-center gap-1.5">
                              <input
                                autoFocus
                                type="text"
                                aria-label="Full name"
                                placeholder="Full name"
                                value={nameDraft}
                                onChange={(e) => setNameDraft(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') saveName(u);
                                  if (e.key === 'Escape') cancelEditName();
                                }}
                                className="w-32 rounded border border-input bg-background px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                              />
                              <button
                                type="button"
                                aria-label="Save name"
                                disabled={savingId === u.id}
                                onClick={() => saveName(u)}
                                className="text-income hover:opacity-80"
                              >
                                <Check className="h-4 w-4" />
                              </button>
                              <button
                                type="button"
                                aria-label="Cancel"
                                onClick={cancelEditName}
                                className="text-muted-foreground hover:text-foreground"
                              >
                                <XCircle className="h-4 w-4" />
                              </button>
                            </div>
                          ) : (
                            <div className="flex items-center gap-1.5 group">
                              <span>{u.full_name || '—'}</span>
                              <button
                                type="button"
                                aria-label="Edit name"
                                onClick={() => startEditName(u)}
                                className="text-muted-foreground/50 hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          )}
                        </td>
                        <td className="py-2.5 pr-3">
                          <Badge variant={u.is_active ? 'income' : 'expense'}>
                            {u.is_active ? 'Active' : 'Inactive'}
                          </Badge>
                        </td>
                        <td className="py-2.5 pr-3">
                          <Select
                            value={u.role ? String(u.role.id) : undefined}
                            onValueChange={(v) => changeRole(u, v)}
                            disabled={isSelf || savingId === u.id}
                          >
                            <SelectTrigger className="w-40 h-8 text-xs" title={isSelf ? "You can't change your own role" : undefined}>
                              <SelectValue placeholder="No role" />
                            </SelectTrigger>
                            <SelectContent>
                              {roles.map((r) => (
                                <SelectItem key={r.id} value={String(r.id)}>{r.name}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="py-2.5 pr-3 text-muted-foreground">{formatDate(u.created_at)}</td>
                        <td className="py-2.5 pr-3">
                          <div className="flex justify-end gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={isSelf || savingId === u.id}
                              title={isSelf ? "You can't change your own status" : undefined}
                              onClick={() => toggleActive(u)}
                            >
                              {u.is_active ? 'Deactivate' : 'Activate'}
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
