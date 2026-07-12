import { useEffect, useState } from 'react';
import { Package, Plus, Pencil, Trash2, XCircle, AlertCircle, AlertTriangle } from 'lucide-react';
import {
  listInventoryItems, createInventoryItem, updateInventoryItem, deleteInventoryItem,
  getInventoryCategories,
} from '../api/client';
import type { InventoryItem, InventoryItemIn } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';

const EMPTY_FORM: InventoryItemIn = {
  name: '',
  sku: '',
  category: '',
  unit: 'piece',
  unit_cost: 0,
  unit_price: 0,
  reorder_level: 0,
  is_active: true,
  notes: '',
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

export function InventoryItems() {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<InventoryItem | null>(null);
  const [form, setForm] = useState<InventoryItemIn>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([listInventoryItems(), getInventoryCategories()])
      .then(([i, c]) => { setItems(i); setCategories(c); })
      .catch(() => setError('Failed to load inventory items'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const openAdd = () => { setEditing(null); setForm(EMPTY_FORM); setShowForm(true); };
  const openEdit = (item: InventoryItem) => {
    setEditing(item);
    setForm({
      name: item.name,
      sku: item.sku ?? '',
      category: item.category,
      unit: item.unit,
      unit_cost: item.unit_cost,
      unit_price: item.unit_price,
      reorder_level: item.reorder_level,
      is_active: item.is_active,
      notes: item.notes ?? '',
    });
    setShowForm(true);
  };
  const closeForm = () => { setShowForm(false); setEditing(null); };

  const handleSave = async () => {
    if (!form.name || !form.category) return;
    setSaving(true);
    try {
      if (editing) {
        await updateInventoryItem(editing.id, form);
      } else {
        await createInventoryItem(form);
      }
      closeForm();
      load();
    } catch {
      setError('Failed to save inventory item');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteInventoryItem(id);
      setDeleteId(null);
      load();
    } catch {
      setError('Failed to delete inventory item');
    }
  };

  const active = items.filter((i) => i.is_active);
  const lowStock = active.filter((i) => i.is_low_stock);
  const totalStockValue = active.reduce((sum, i) => sum + i.quantity_on_hand * i.unit_cost, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Package className="h-6 w-6 text-primary" />
            Inventory Items
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Catalog of books, uniforms, and textbooks — restock and sell via Stock Requests
          </p>
        </div>
        <Button onClick={openAdd}>
          <Plus className="h-4 w-4 mr-1" />
          Add Item
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Active Items</p>
            <p className="text-xl font-bold mt-1">{active.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Low Stock</p>
            <p className={`text-xl font-bold mt-1 ${lowStock.length > 0 ? 'text-destructive' : ''}`}>
              {lowStock.length}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Stock Value (at cost)</p>
            <p className="text-xl font-bold mt-1">{formatCurrency(totalStockValue)}</p>
          </CardContent>
        </Card>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Items</CardTitle>
          </CardHeader>
          <CardContent>
            {items.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">
                No items added yet. Click "Add Item" to create the catalog.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs text-muted-foreground">
                      <th className="text-left py-2 pr-4 font-medium">Name</th>
                      <th className="text-left py-2 pr-4 font-medium">Category</th>
                      <th className="text-left py-2 pr-4 font-medium">SKU</th>
                      <th className="text-right py-2 pr-4 font-medium">On Hand</th>
                      <th className="text-right py-2 pr-4 font-medium">Unit Cost</th>
                      <th className="text-right py-2 pr-4 font-medium">Unit Price</th>
                      <th className="py-2"><span className="sr-only">Actions</span></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {items.map((i) => (
                      <tr key={i.id} className={`hover:bg-muted/30 transition-colors ${!i.is_active ? 'opacity-50' : ''}`}>
                        <td className="py-3 pr-4 font-medium">{i.name}</td>
                        <td className="py-3 pr-4 text-muted-foreground">{i.category}</td>
                        <td className="py-3 pr-4">
                          {i.sku ? <span className="font-mono text-xs bg-muted px-2 py-0.5 rounded">{i.sku}</span> : '—'}
                        </td>
                        <td className="py-3 pr-4 text-right font-medium">
                          <span className="inline-flex items-center gap-1 justify-end">
                            {i.is_low_stock && (
                              <AlertTriangle className="h-3.5 w-3.5 text-destructive" aria-label="Low stock" />
                            )}
                            {i.quantity_on_hand} {i.unit}
                          </span>
                        </td>
                        <td className="py-3 pr-4 text-right text-muted-foreground">{formatCurrency(i.unit_cost)}</td>
                        <td className="py-3 pr-4 text-right text-muted-foreground">{formatCurrency(i.unit_price)}</td>
                        <td className="py-3">
                          <div className="flex gap-1 justify-end">
                            <button
                              type="button"
                              aria-label="Edit"
                              onClick={() => openEdit(i)}
                              className="p-1.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              aria-label="Delete"
                              onClick={() => setDeleteId(i.id)}
                              className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
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
              <h2 className="text-lg font-semibold">{editing ? 'Edit Item' : 'Add Item'}</h2>
              <button type="button" aria-label="Close" onClick={closeForm} className="text-muted-foreground hover:text-foreground">
                <XCircle className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Name *</label>
                <input
                  type="text"
                  placeholder="e.g. Grade 5 Maths Textbook"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">Category *</label>
                  <select
                    title="Category"
                    value={form.category}
                    onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="">Select category…</option>
                    {categories.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-foreground mb-1">SKU</label>
                  <input
                    type="text"
                    placeholder="Optional"
                    value={form.sku ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, sku: e.target.value }))}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Unit</label>
                <input
                  type="text"
                  placeholder="piece"
                  value={form.unit ?? 'piece'}
                  onChange={(e) => setForm((f) => ({ ...f, unit: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <NumInput label="Unit Cost" value={form.unit_cost ?? 0} onChange={(n) => setForm((f) => ({ ...f, unit_cost: n }))} />
                <NumInput label="Unit Price" value={form.unit_price ?? 0} onChange={(n) => setForm((f) => ({ ...f, unit_price: n }))} />
              </div>

              <NumInput
                label="Reorder Level (low-stock threshold)"
                value={form.reorder_level ?? 0}
                onChange={(n) => setForm((f) => ({ ...f, reorder_level: n }))}
              />

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

              <div className="flex items-center gap-2">
                <input
                  id="is_active_item"
                  type="checkbox"
                  checked={form.is_active ?? true}
                  onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                  className="rounded border-input"
                />
                <label htmlFor="is_active_item" className="text-sm">Active item</label>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={closeForm} disabled={saving}>Cancel</Button>
              <Button onClick={handleSave} disabled={saving || !form.name || !form.category}>
                {saving ? 'Saving…' : editing ? 'Save Changes' : 'Add Item'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {deleteId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm bg-card rounded-xl shadow-xl border border-border p-6 space-y-4">
            <h2 className="text-base font-semibold">Remove Item?</h2>
            <p className="text-sm text-muted-foreground">
              This removes the item from the catalog along with any pending or fulfilled stock requests
              for it. Its stock movement ledger rows are kept, but will show without an item name once
              it's gone. To keep the item's name in the ledger, uncheck "Active" via Edit instead.
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
