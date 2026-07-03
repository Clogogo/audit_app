import { useEffect, useState } from 'react';
import { Shield, Plus, Pencil, Trash2, AlertCircle, XCircle } from 'lucide-react';
import { listRoles, listPermissions, createRole, updateRole, deleteRole } from '../api/client';
import type { Permission, Role, RoleIn } from '../api/types';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';

const EMPTY_ROLE: RoleIn = { name: '', description: '', permission_keys: [] };

export function RoleManagement() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [showForm, setShowForm] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [form, setForm] = useState<RoleIn>(EMPTY_ROLE);
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    Promise.all([listRoles(), listPermissions()])
      .then(([r, p]) => { setRoles(r); setPermissions(p); })
      .catch(() => setError('Failed to load roles'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const openAdd = () => { setEditingRole(null); setForm(EMPTY_ROLE); setShowForm(true); };
  const openEdit = (role: Role) => {
    setEditingRole(role);
    setForm({ name: role.name, description: role.description ?? '', permission_keys: [...role.permissions] });
    setShowForm(true);
  };

  const togglePermission = (key: string) => {
    setForm((f) => ({
      ...f,
      permission_keys: f.permission_keys.includes(key)
        ? f.permission_keys.filter((k) => k !== key)
        : [...f.permission_keys, key],
    }));
  };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      if (editingRole) {
        await updateRole(editingRole.id, form);
      } else {
        await createRole(form);
      }
      setShowForm(false);
      load();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to save role');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setError(null);
    try {
      await deleteRole(deleteTarget.id);
      setDeleteTarget(null);
      load();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to delete role');
      setDeleteTarget(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Shield className="h-6 w-6 text-primary" />
            Role Management
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Define which sections of the app each role can access
          </p>
        </div>
        <Button onClick={openAdd}>
          <Plus className="h-4 w-4 mr-1" />
          Add Role
        </Button>
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

      {loading ? (
        <p className="text-sm text-muted-foreground py-4 text-center">Loading…</p>
      ) : (
        <div className="space-y-3">
          {roles.map((role) => (
            <Card key={role.id}>
              <CardContent className="pt-5">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-semibold text-sm">{role.name}</p>
                      {role.is_system && <Badge variant="outline">System</Badge>}
                    </div>
                    {role.description && (
                      <p className="text-xs text-muted-foreground mt-0.5">{role.description}</p>
                    )}
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {role.permissions.length === 0 ? (
                        <span className="text-xs text-muted-foreground">No permissions granted</span>
                      ) : (
                        permissions
                          .filter((p) => role.permissions.includes(p.key))
                          .map((p) => <Badge key={p.key} variant="secondary">{p.label}</Badge>)
                      )}
                    </div>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <button type="button" aria-label="Edit role" onClick={() => openEdit(role)}
                      className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      aria-label="Delete role"
                      disabled={role.is_system}
                      title={role.is_system ? 'System roles cannot be deleted' : undefined}
                      onClick={() => setDeleteTarget(role)}
                      className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive disabled:opacity-40 disabled:hover:bg-transparent"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Add/Edit Role modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md bg-card rounded-xl shadow-xl border border-border p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{editingRole ? 'Edit Role' : 'Add Role'}</h2>
              <button type="button" aria-label="Close" onClick={() => setShowForm(false)} className="text-muted-foreground hover:text-foreground">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Name *</label>
                <input
                  type="text"
                  placeholder="e.g. Front Desk"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Description</label>
                <input
                  type="text"
                  placeholder="Optional"
                  value={form.description ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-2">Permissions</label>
                <div className="space-y-2">
                  {permissions.map((p) => (
                    <label key={p.key} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={form.permission_keys.includes(p.key)}
                        onChange={() => togglePermission(p.key)}
                        className="rounded border-input"
                      />
                      {p.label}
                    </label>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowForm(false)} disabled={saving}>Cancel</Button>
              <Button onClick={handleSave} disabled={saving || !form.name.trim()}>
                {saving ? 'Saving…' : editingRole ? 'Save Changes' : 'Add Role'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <h2 className="text-base font-semibold">Delete "{deleteTarget.name}"?</h2>
            <p className="text-sm text-muted-foreground">
              This can't be undone. Roles currently assigned to a user can't be deleted — reassign them first.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
              <Button variant="destructive" onClick={handleDelete}>Delete</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
