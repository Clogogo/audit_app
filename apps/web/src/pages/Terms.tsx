import { useEffect, useState } from 'react';
import { CalendarRange, Plus, Pencil, Trash2, AlertCircle, XCircle } from 'lucide-react';
import { getTerms, createTerm, updateTerm, deleteTerm } from '../api/client';
import type { Term, TermCreate } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';

const EMPTY_FORM: TermCreate = { name: '', start_date: '', end_date: '' };

function formatRange(start: string, end: string) {
  const opts: Intl.DateTimeFormatOptions = { day: '2-digit', month: 'short', year: 'numeric' };
  return `${new Date(start).toLocaleDateString('en-NG', opts)} – ${new Date(end).toLocaleDateString('en-NG', opts)}`;
}

export function Terms() {
  const [terms, setTerms] = useState<Term[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editingTerm, setEditingTerm] = useState<Term | null>(null);
  const [form, setForm] = useState<TermCreate>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    getTerms()
      .then(setTerms)
      .catch(() => setError('Failed to load terms'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const openAdd = () => { setEditingTerm(null); setForm(EMPTY_FORM); setError(null); setShowForm(true); };
  const openEdit = (t: Term) => {
    setEditingTerm(t);
    setForm({ name: t.name, start_date: t.start_date, end_date: t.end_date });
    setError(null);
    setShowForm(true);
  };
  const closeForm = () => { setShowForm(false); setEditingTerm(null); };

  const handleSave = async () => {
    if (!form.name.trim() || !form.start_date || !form.end_date) {
      setError('Name, start date, and end date are all required.');
      return;
    }
    if (form.end_date < form.start_date) {
      setError('End date must be on or after the start date.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editingTerm) {
        await updateTerm(editingTerm.id, form);
      } else {
        await createTerm(form);
      }
      closeForm();
      load();
    } catch {
      setError(editingTerm ? 'Failed to update term.' : 'Failed to create term.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteTerm(id);
      setDeleteId(null);
      load();
    } catch {
      setError('Failed to delete term.');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <CalendarRange className="h-6 w-6 text-primary" />
            Terms
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Named custom date ranges (e.g. school terms) — reusable as a filter on Dashboard and Transactions
          </p>
        </div>
        <Button onClick={openAdd}>
          <Plus className="h-4 w-4 mr-1" />
          Add Term
        </Button>
      </div>

      {error && !showForm && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">All Terms</CardTitle>
          </CardHeader>
          <CardContent>
            {terms.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No terms yet. Click "Add Term" to create one.
              </p>
            ) : (
              <div className="divide-y divide-border">
                {terms.map((t) => (
                  <div key={t.id} className="flex items-center justify-between py-3 gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{t.name}</p>
                      <p className="text-xs text-muted-foreground">{formatRange(t.start_date, t.end_date)}</p>
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <button
                        type="button"
                        aria-label="Edit term"
                        onClick={() => openEdit(t)}
                        className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        aria-label="Delete term"
                        onClick={() => setDeleteId(t.id)}
                        className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Form modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{editingTerm ? 'Edit Term' : 'Add Term'}</h2>
              <button type="button" aria-label="Close" onClick={closeForm} className="text-muted-foreground hover:text-foreground">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Name *</label>
                <input
                  type="text"
                  placeholder="e.g. Term 1 2025/2026"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">Start Date *</label>
                  <input
                    type="date"
                    title="Term start date"
                    value={form.start_date}
                    onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">End Date *</label>
                  <input
                    type="date"
                    title="Term end date"
                    value={form.end_date}
                    onChange={(e) => setForm((f) => ({ ...f, end_date: e.target.value }))}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={closeForm} disabled={saving}>Cancel</Button>
              <Button onClick={handleSave} disabled={saving}>
                {saving ? 'Saving…' : editingTerm ? 'Save Changes' : 'Add Term'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {deleteId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <h2 className="text-base font-semibold">Remove Term?</h2>
            <p className="text-sm text-muted-foreground">
              This removes the term. Dashboard and Transactions filters using it will fall back to no term selected.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDeleteId(null)}>Cancel</Button>
              <Button variant="destructive" onClick={() => handleDelete(deleteId)}>Remove</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
