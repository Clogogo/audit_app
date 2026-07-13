import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { History, SlidersHorizontal, XCircle, AlertCircle } from 'lucide-react';
import { listStockMovements, adjustStock, listInventoryItems, getSalesSummary } from '../api/client';
import type { StockMovement, StockMovementType, StockAdjustmentIn, InventoryItem, SalesSummary } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { formatCurrency } from '../lib/utils';

const todayISO = () => new Date().toISOString().slice(0, 10);

const emptyAdjustment = (): StockAdjustmentIn => ({
  item_id: 0,
  movement_type: 'adjustment_in',
  quantity: 0,
  date: todayISO(),
  notes: '',
});

const typeLabel: Record<StockMovementType, string> = {
  purchase_in: 'Purchase In',
  sale_out: 'Sale Out',
  adjustment_in: 'Adjustment In',
  adjustment_out: 'Adjustment Out',
};

const typeVariant: Record<StockMovementType, 'income' | 'expense' | 'secondary'> = {
  purchase_in: 'income',
  sale_out: 'expense',
  adjustment_in: 'income',
  adjustment_out: 'expense',
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

export function StockMovements() {
  const [searchParams] = useSearchParams();
  const [movements, setMovements] = useState<StockMovement[]>([]);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [salesSummary, setSalesSummary] = useState<SalesSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Preset from a deep link (e.g. the Inventory Report's "View Ledger"),
  // read once on mount — this filter is otherwise fully user-driven.
  const [itemFilter, setItemFilter] = useState(() => searchParams.get('item') || 'all');
  const [typeFilter, setTypeFilter] = useState('all');

  const [showAdjustForm, setShowAdjustForm] = useState(false);
  const [form, setForm] = useState<StockAdjustmentIn>(emptyAdjustment());
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([listStockMovements(), listInventoryItems({ active_only: true })])
      .then(([m, i]) => { setMovements(m); setItems(i); })
      .catch(() => setError('Failed to load stock movements'))
      .finally(() => setLoading(false));

    // Fetched independently — a failure here is a missing summary widget,
    // not a reason to fail the whole ledger page.
    getSalesSummary().then(setSalesSummary).catch(() => setSalesSummary(null));
  };

  useEffect(() => { load(); }, []);

  const handleAdjust = async () => {
    if (!form.item_id || form.quantity <= 0 || !form.date) return;
    setSaving(true);
    try {
      await adjustStock(form);
      setShowAdjustForm(false);
      setForm(emptyAdjustment());
      load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to record adjustment');
    } finally {
      setSaving(false);
    }
  };

  const filtered = movements.filter(
    (m) =>
      (itemFilter === 'all' || String(m.item_id) === itemFilter) &&
      (typeFilter === 'all' || m.movement_type === typeFilter)
  );

  const fmtDate = (d: string) => new Date(d).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <History className="h-6 w-6 text-primary" />
            Stock Movements
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Append-only ledger of every quantity change — fulfilled requests and manual adjustments
          </p>
        </div>
        <Button onClick={() => setShowAdjustForm(true)} disabled={items.length === 0}>
          <SlidersHorizontal className="h-4 w-4 mr-1" />
          Adjust Stock
        </Button>
      </div>

      {salesSummary && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Card>
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Sales Revenue</p>
              <p className="text-xl font-bold mt-1 text-income">{formatCurrency(salesSummary.total_revenue)}</p>
              <p className="text-xs text-muted-foreground mt-1">{salesSummary.total_sales_count} sale(s)</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Profit</p>
              <p className="text-xl font-bold mt-1">{formatCurrency(salesSummary.total_profit)}</p>
              {salesSummary.sales_missing_cost_count > 0 && (
                <p className="text-xs text-muted-foreground mt-1">
                  Excludes {salesSummary.sales_missing_cost_count} sale(s) with no recorded cost
                </p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Profit Margin</p>
              <p className="text-xl font-bold mt-1">{salesSummary.profit_margin_pct.toFixed(1)}%</p>
            </CardContent>
          </Card>
        </div>
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

      <div className="flex items-center gap-3 flex-wrap">
        <Select value={itemFilter} onValueChange={setItemFilter}>
          <SelectTrigger className="w-56"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Items</SelectItem>
            {items.map((i) => (
              <SelectItem key={i.id} value={String(i.id)}>{i.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Movement Types</SelectItem>
            <SelectItem value="purchase_in">Purchase In</SelectItem>
            <SelectItem value="sale_out">Sale Out</SelectItem>
            <SelectItem value="adjustment_in">Adjustment In</SelectItem>
            <SelectItem value="adjustment_out">Adjustment Out</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="text-center py-16 text-muted-foreground">Loading…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">No stock movements match this filter</div>
      ) : (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Ledger</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[700px]">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="text-left py-2 pr-3 font-medium">Date</th>
                    <th className="text-left py-2 pr-3 font-medium">Item</th>
                    <th className="text-left py-2 pr-3 font-medium">Type</th>
                    <th className="text-right py-2 pr-3 font-medium">Quantity</th>
                    <th className="text-right py-2 pr-3 font-medium">Unit Amount</th>
                    <th className="text-right py-2 pr-3 font-medium">Profit</th>
                    <th className="text-left py-2 pr-3 font-medium">Source</th>
                    <th className="text-left py-2 font-medium">Notes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {filtered.map((m) => (
                    <tr key={m.id} className="hover:bg-muted/30 transition-colors">
                      <td className="py-3 pr-3 whitespace-nowrap text-muted-foreground">{fmtDate(m.date)}</td>
                      <td className="py-3 pr-3 font-medium">{m.item_name || '—'}</td>
                      <td className="py-3 pr-3">
                        <Badge variant={typeVariant[m.movement_type]}>{typeLabel[m.movement_type] ?? m.movement_type}</Badge>
                      </td>
                      <td className="py-3 pr-3 text-right">{m.quantity}</td>
                      <td className="py-3 pr-3 text-right text-muted-foreground">
                        {m.unit_amount !== null ? formatCurrency(m.unit_amount) : '—'}
                      </td>
                      <td className="py-3 pr-3 text-right text-muted-foreground">
                        {m.movement_type === 'sale_out' && m.unit_amount !== null && m.unit_cost !== null
                          ? formatCurrency((m.unit_amount - m.unit_cost) * m.quantity)
                          : '—'}
                      </td>
                      <td className="py-3 pr-3 text-muted-foreground">
                        {m.request_id ? `Request #${m.request_id}` : 'Manual adjustment'}
                      </td>
                      <td className="py-3 text-xs text-muted-foreground">{m.notes || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Manual adjustment modal */}
      {showAdjustForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md bg-card rounded-xl shadow-xl border border-border p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Adjust Stock</h2>
              <button type="button" aria-label="Close" onClick={() => setShowAdjustForm(false)} className="text-muted-foreground hover:text-foreground">
                <XCircle className="h-5 w-5" />
              </button>
            </div>
            <p className="text-xs text-muted-foreground">
              For corrections outside a purchase or sale — a physical count, damage, or loss. This bypasses
              the request workflow and updates stock immediately.
            </p>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Item *</label>
                <select
                  title="Select item"
                  value={form.item_id || ''}
                  onChange={(e) => setForm((f) => ({ ...f, item_id: e.target.value ? parseInt(e.target.value, 10) : 0 }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">— Select item —</option>
                  {items.map((i) => (
                    <option key={i.id} value={i.id}>{i.name} ({i.quantity_on_hand} {i.unit} on hand)</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Direction *</label>
                <div className="flex gap-2">
                  {(['adjustment_in', 'adjustment_out'] as const).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, movement_type: t }))}
                      className={`flex-1 rounded-md border px-3 py-2 text-sm ${
                        form.movement_type === t ? 'border-primary bg-primary/10 text-primary font-medium' : 'border-input text-muted-foreground'
                      }`}
                    >
                      {t === 'adjustment_in' ? 'Add Stock' : 'Remove Stock'}
                    </button>
                  ))}
                </div>
              </div>

              <NumInput label="Quantity *" value={form.quantity} onChange={(n) => setForm((f) => ({ ...f, quantity: n }))} />

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Date *</label>
                <input
                  type="date"
                  title="Adjustment date"
                  value={form.date}
                  onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-foreground mb-1">Notes</label>
                <input
                  type="text"
                  placeholder="Reason for the adjustment"
                  value={form.notes ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowAdjustForm(false)} disabled={saving}>Cancel</Button>
              <Button onClick={handleAdjust} disabled={saving || !form.item_id || form.quantity <= 0}>
                {saving ? 'Saving…' : 'Record Adjustment'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
