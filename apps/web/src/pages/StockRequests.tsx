import { useEffect, useState } from 'react';
import { ClipboardList, Plus, Pencil, Trash2, XCircle, AlertCircle, CheckCircle2, Ban } from 'lucide-react';
import {
  listStockRequests, createStockRequest, updateStockRequest, deleteStockRequest,
  fulfillStockRequest, cancelStockRequest, listInventoryItems,
} from '../api/client';
import type { StockRequest, StockRequestIn, StockRequestType, InventoryItem } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { formatCurrency } from '../lib/utils';

const todayISO = () => new Date().toISOString().slice(0, 10);

const emptyForm = (): StockRequestIn => ({
  item_id: 0,
  request_type: 'purchase',
  quantity: 0,
  unit_amount: 0,
  counterparty: '',
  request_date: todayISO(),
  notes: '',
});

const statusVariant: Record<string, 'secondary' | 'income' | 'destructive'> = {
  pending: 'secondary',
  fulfilled: 'income',
  cancelled: 'destructive',
};

function NumInput({ label, value, onChange }: {
  label: string; value: number; onChange: (n: number) => void;
}) {
  const [raw, setRaw] = useState('');
  const [focused, setFocused] = useState(false);
  return (
    <div>
      <label className="block text-xs font-medium text-foreground mb-1">{label}</label>
      <input
        type="text"
        inputMode="numeric"
        placeholder="0"
        value={focused ? raw : (value === 0 ? '' : value.toLocaleString('en-NG'))}
        onFocus={() => { setFocused(true); setRaw(value === 0 ? '' : String(value)); }}
        onChange={(e) => {
          const d = e.target.value.replace(/[^0-9]/g, '');
          setRaw(d);
          onChange(d === '' ? 0 : parseInt(d, 10));
        }}
        onBlur={() => setFocused(false)}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
    </div>
  );
}

export function StockRequests() {
  const [requests, setRequests] = useState<StockRequest[]>([]);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [typeFilter, setTypeFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<StockRequest | null>(null);
  const [form, setForm] = useState<StockRequestIn>(emptyForm());
  const [saving, setSaving] = useState(false);

  const [confirmAction, setConfirmAction] = useState<{ type: 'fulfill' | 'cancel' | 'delete'; request: StockRequest } | null>(null);
  const [acting, setActing] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([listStockRequests(), listInventoryItems({ active_only: true })])
      .then(([r, i]) => { setRequests(r); setItems(i); })
      .catch(() => setError('Failed to load stock requests'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const openAdd = () => { setEditing(null); setForm(emptyForm()); setShowForm(true); };
  const openEdit = (req: StockRequest) => {
    setEditing(req);
    setForm({
      item_id: req.item_id,
      request_type: req.request_type,
      quantity: req.quantity,
      unit_amount: req.unit_amount,
      counterparty: req.counterparty ?? '',
      request_date: req.request_date,
      notes: req.notes ?? '',
    });
    setShowForm(true);
  };
  const closeForm = () => { setShowForm(false); setEditing(null); };

  const applyDefaultUnitAmount = (itemId: number, requestType: StockRequestType) => {
    const item = items.find((i) => i.id === itemId);
    if (!item) return;
    setForm((f) => ({ ...f, unit_amount: requestType === 'purchase' ? item.unit_cost : item.unit_price }));
  };

  const handleSave = async () => {
    if (!form.item_id || form.quantity <= 0 || !form.request_date) return;
    setSaving(true);
    try {
      if (editing) {
        await updateStockRequest(editing.id, form);
      } else {
        await createStockRequest(form);
      }
      closeForm();
      load();
    } catch {
      setError('Failed to save stock request');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (req: StockRequest) => {
    try {
      await deleteStockRequest(req.id);
      setConfirmAction(null);
      load();
    } catch {
      setError('Failed to delete stock request');
    }
  };

  const handleFulfill = async (req: StockRequest) => {
    setActing(true);
    try {
      await fulfillStockRequest(req.id);
      setConfirmAction(null);
      load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to fulfill request — check available stock');
      setConfirmAction(null);
    } finally {
      setActing(false);
    }
  };

  const handleCancel = async (req: StockRequest) => {
    setActing(true);
    try {
      await cancelStockRequest(req.id);
      setConfirmAction(null);
      load();
    } catch {
      setError('Failed to cancel stock request');
      setConfirmAction(null);
    } finally {
      setActing(false);
    }
  };

  const filtered = requests.filter(
    (r) => (typeFilter === 'all' || r.request_type === typeFilter) && (statusFilter === 'all' || r.status === statusFilter)
  );
  const pendingCount = requests.filter((r) => r.status === 'pending').length;
  const pendingPurchaseValue = requests
    .filter((r) => r.status === 'pending' && r.request_type === 'purchase')
    .reduce((sum, r) => sum + r.quantity * r.unit_amount, 0);
  const pendingSaleValue = requests
    .filter((r) => r.status === 'pending' && r.request_type === 'sale')
    .reduce((sum, r) => sum + r.quantity * r.unit_amount, 0);

  const fmtDate = (d: string) => new Date(d).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <ClipboardList className="h-6 w-6 text-primary" />
            Stock Requests
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Purchase requests restock an item; sale requests issue or sell it. Fulfilling one moves stock.
          </p>
        </div>
        <Button onClick={openAdd} disabled={items.length === 0}>
          <Plus className="h-4 w-4 mr-1" />
          New Request
        </Button>
      </div>

      {items.length === 0 && !loading && (
        <p className="text-xs text-amber-700">
          No active items in the catalog yet. <a href="/inventory/items" className="underline">Add an item first.</a>
        </p>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
          <button type="button" title="Dismiss error" className="ml-auto text-destructive/80 hover:text-destructive" onClick={() => setError(null)}>
            <XCircle className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Pending Requests</p>
            <p className="text-xl font-bold mt-1">{pendingCount}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Pending Purchases (value)</p>
            <p className="text-xl font-bold mt-1 text-expense">{formatCurrency(pendingPurchaseValue)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Pending Sales (value)</p>
            <p className="text-xl font-bold mt-1 text-income">{formatCurrency(pendingSaleValue)}</p>
          </CardContent>
        </Card>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="purchase">Purchase</SelectItem>
            <SelectItem value="sale">Sale</SelectItem>
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="fulfilled">Fulfilled</SelectItem>
            <SelectItem value="cancelled">Cancelled</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Requests</CardTitle>
          </CardHeader>
          <CardContent>
            {filtered.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">No requests match this filter.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs text-muted-foreground">
                      <th className="text-left py-2 pr-3 font-medium">Item</th>
                      <th className="text-left py-2 pr-3 font-medium">Type</th>
                      <th className="text-right py-2 pr-3 font-medium">Qty</th>
                      <th className="text-right py-2 pr-3 font-medium">Unit Amount</th>
                      <th className="text-right py-2 pr-3 font-medium">Total</th>
                      <th className="text-left py-2 pr-3 font-medium">Counterparty</th>
                      <th className="text-left py-2 pr-3 font-medium">Date</th>
                      <th className="text-left py-2 pr-3 font-medium">Status</th>
                      <th className="py-2"><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {filtered.map((r) => (
                      <tr key={r.id} className="hover:bg-muted/30 transition-colors">
                        <td className="py-3 pr-3 font-medium">{r.item_name}</td>
                        <td className="py-3 pr-3 capitalize">{r.request_type}</td>
                        <td className="py-3 pr-3 text-right">{r.quantity}</td>
                        <td className="py-3 pr-3 text-right text-muted-foreground">{formatCurrency(r.unit_amount)}</td>
                        <td className="py-3 pr-3 text-right font-medium">{formatCurrency(r.quantity * r.unit_amount)}</td>
                        <td className="py-3 pr-3 text-muted-foreground">{r.counterparty || '—'}</td>
                        <td className="py-3 pr-3 text-muted-foreground">{fmtDate(r.request_date)}</td>
                        <td className="py-3 pr-3">
                          <Badge variant={statusVariant[r.status]} className="capitalize">{r.status}</Badge>
                        </td>
                        <td className="py-3">
                          {r.status === 'pending' && (
                            <div className="flex gap-1 justify-end">
                              <button
                                type="button"
                                aria-label="Fulfill"
                                title="Fulfill — moves stock"
                                onClick={() => setConfirmAction({ type: 'fulfill', request: r })}
                                className="p-1.5 rounded hover:bg-green-100 text-muted-foreground hover:text-green-700"
                              >
                                <CheckCircle2 className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                aria-label="Cancel"
                                title="Cancel request"
                                onClick={() => setConfirmAction({ type: 'cancel', request: r })}
                                className="p-1.5 rounded hover:bg-accent text-muted-foreground"
                              >
                                <Ban className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                aria-label="Edit"
                                onClick={() => openEdit(r)}
                                className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                aria-label="Delete"
                                onClick={() => setConfirmAction({ type: 'delete', request: r })}
                                className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Form modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md bg-card rounded-xl shadow-xl border border-border p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">{editing ? 'Edit Request' : 'New Stock Request'}</h2>
              <button type="button" aria-label="Close" onClick={closeForm} className="text-muted-foreground hover:text-foreground">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Type *</label>
                <div className="flex gap-2">
                  {(['purchase', 'sale'] as StockRequestType[]).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => {
                        setForm((f) => ({ ...f, request_type: t }));
                        if (form.item_id) applyDefaultUnitAmount(form.item_id, t);
                      }}
                      className={`flex-1 rounded-md border px-3 py-2 text-sm capitalize ${
                        form.request_type === t ? 'border-primary bg-primary/10 text-primary font-medium' : 'border-input text-muted-foreground'
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Item *</label>
                <select
                  title="Select item"
                  value={form.item_id || ''}
                  onChange={(e) => {
                    const id = e.target.value ? parseInt(e.target.value, 10) : 0;
                    setForm((f) => ({ ...f, item_id: id }));
                    if (id) applyDefaultUnitAmount(id, form.request_type);
                  }}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">— Select item —</option>
                  {items.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name} ({i.quantity_on_hand} {i.unit} on hand)
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <NumInput label="Quantity *" value={form.quantity} onChange={(n) => setForm((f) => ({ ...f, quantity: n }))} />
                <NumInput
                  label={form.request_type === 'purchase' ? 'Unit Cost' : 'Unit Price'}
                  value={form.unit_amount}
                  onChange={(n) => setForm((f) => ({ ...f, unit_amount: n }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">
                  {form.request_type === 'purchase' ? 'Supplier' : 'Buyer'}
                </label>
                <input
                  type="text"
                  placeholder="Optional"
                  value={form.counterparty ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, counterparty: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Request Date *</label>
                <input
                  type="date"
                  title="Request date"
                  value={form.request_date}
                  onChange={(e) => setForm((f) => ({ ...f, request_date: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Notes</label>
                <input
                  type="text"
                  placeholder="Optional"
                  value={form.notes ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={closeForm} disabled={saving}>Cancel</Button>
              <Button onClick={handleSave} disabled={saving || !form.item_id || form.quantity <= 0}>
                {saving ? 'Saving…' : editing ? 'Save Changes' : 'Create Request'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm fulfill / cancel / delete */}
      {confirmAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <h2 className="text-base font-semibold">
              {confirmAction.type === 'fulfill' && 'Fulfill this request?'}
              {confirmAction.type === 'cancel' && 'Cancel this request?'}
              {confirmAction.type === 'delete' && 'Delete this request?'}
            </h2>
            <p className="text-sm text-muted-foreground">
              {confirmAction.type === 'fulfill' &&
                `This will ${confirmAction.request.request_type === 'purchase' ? 'add' : 'remove'} ${confirmAction.request.quantity} ${confirmAction.request.request_type === 'purchase' ? 'to' : 'from'} ${confirmAction.request.item_name}'s stock and log a movement. This cannot be undone.`}
              {confirmAction.type === 'cancel' && 'The request will be marked cancelled and no stock will move.'}
              {confirmAction.type === 'delete' && 'This will permanently remove the pending request.'}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setConfirmAction(null)} disabled={acting}>Back</Button>
              <Button
                variant={confirmAction.type === 'delete' ? 'destructive' : 'default'}
                disabled={acting}
                onClick={() => {
                  if (confirmAction.type === 'fulfill') handleFulfill(confirmAction.request);
                  else if (confirmAction.type === 'cancel') handleCancel(confirmAction.request);
                  else handleDelete(confirmAction.request);
                }}
              >
                {acting ? 'Working…' : 'Confirm'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
