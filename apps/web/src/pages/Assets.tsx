import { useEffect, useState } from 'react';
import {
  Building2, Plus, Pencil, Trash2, Package, TrendingDown, DollarSign, Calendar,
} from 'lucide-react';
import {
  getAssets, getAssetCategories, createAsset, updateAsset, deleteAsset,
} from '../api/client';
import type { Asset, AssetCreate } from '../api/types';
import { useNotification } from '../hooks';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { ConfirmDialog } from '../components/ConfirmDialog';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '../components/ui/dialog';
import { formatCurrency } from '../lib/utils';
import { HelpTooltip } from '../components/HelpTooltip';

const DEPRECIATION_METHODS = [
  { value: 'straight_line', label: 'Straight-Line' },
  { value: 'reducing_balance', label: 'Reducing Balance' },
];

function emptyForm(): AssetCreate {
  return {
    name: '',
    category: '',
    purchase_date: '',
    purchase_cost: 0,
    useful_life_years: 5,
    depreciation_method: 'straight_line',
    residual_value: 0,
    notes: '',
  };
}

export function Assets() {
  const notify = useNotification();

  const [assets, setAssets] = useState<Asset[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<AssetCreate>(emptyForm());
  const [formError, setFormError] = useState('');

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Asset | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([getAssets(), getAssetCategories()])
      .then(([a, c]) => { setAssets(a); setCategories(c); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const openAdd = () => {
    setEditingId(null);
    setForm(emptyForm());
    setFormError('');
    setDialogOpen(true);
  };

  const openEdit = (asset: Asset) => {
    setEditingId(asset.id);
    setForm({
      name: asset.name,
      category: asset.category,
      purchase_date: asset.purchase_date,
      purchase_cost: asset.purchase_cost,
      useful_life_years: asset.useful_life_years,
      depreciation_method: asset.depreciation_method,
      residual_value: asset.residual_value,
      notes: asset.notes ?? '',
    });
    setFormError('');
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) { setFormError('Asset name is required'); return; }
    if (!form.category) { setFormError('Category is required'); return; }
    if (!form.purchase_date) { setFormError('Purchase date is required'); return; }
    if (form.purchase_cost <= 0) { setFormError('Purchase cost must be greater than 0'); return; }
    if (form.useful_life_years <= 0) { setFormError('Useful life must be greater than 0'); return; }
    if (form.residual_value < 0) { setFormError('Residual value cannot be negative'); return; }
    if (form.residual_value >= form.purchase_cost) { setFormError('Residual value must be less than purchase cost'); return; }

    setSaving(true);
    setFormError('');
    try {
      const payload = { ...form, notes: form.notes || undefined };
      if (editingId) {
        await updateAsset(editingId, payload);
        notify.success('Asset updated');
      } else {
        await createAsset(payload);
        notify.success('Asset added');
      }
      setDialogOpen(false);
      load();
    } catch {
      setFormError('Failed to save asset. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteClick = (asset: Asset) => {
    setDeleteTarget(asset);
    setConfirmOpen(true);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteAsset(deleteTarget.id);
      notify.success('Asset deleted');
      setConfirmOpen(false);
      setDeleteTarget(null);
      load();
    } catch {
      notify.error('Failed to delete asset');
    } finally {
      setDeleting(false);
    }
  };

  // KPI totals
  const totalCost = assets.reduce((s, a) => s + a.purchase_cost, 0);
  const totalNBV = assets.reduce((s, a) => s + a.net_book_value, 0);
  const totalAnnualDep = assets.reduce((s, a) => s + (a.annual_depreciation ?? 0), 0);

  // Annual depreciation preview for the form
  const previewAnnualDep =
    form.useful_life_years > 0 && form.purchase_cost > 0
      ? (form.purchase_cost - form.residual_value) / form.useful_life_years
      : 0;

  const groupedByCategory = assets.reduce<Record<string, Asset[]>>((acc, a) => {
    acc[a.category] = acc[a.category] ?? [];
    acc[a.category].push(a);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Package className="h-6 w-6 text-primary" />
            Asset Register
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Fixed assets with computed depreciation — feeds into Financial Statements and CIT
          </p>
        </div>
        <Button onClick={openAdd}>
          <Plus className="h-4 w-4 mr-1" />
          Add Asset
        </Button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-5 pb-4 px-5">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1">
                  Total Cost
                  <HelpTooltip
                    title="Total Cost"
                    align="left"
                    content={"Sum of all asset purchase costs — the gross historical cost before any depreciation.\n\nExample:\nSchool Bus: ₦5,500,000\nComputers (10): ₦3,200,000\nFurniture: ₦800,000\n────────────────\nTotal Cost: ₦9,500,000"}
                  />
                </p>
                <p className="text-xl font-bold text-foreground mt-1">{formatCurrency(totalCost)}</p>
                <p className="text-xs text-muted-foreground mt-0.5">{assets.length} asset{assets.length !== 1 ? 's' : ''}</p>
              </div>
              <DollarSign className="h-8 w-8 text-primary/30" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5 pb-4 px-5">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1">
                  Net Book Value
                  <HelpTooltip
                    title="Net Book Value (NBV)"
                    content={"NBV = Purchase Cost − Accumulated Depreciation\n\nThis is the current carrying value shown in the Financial Statements balance sheet under Non-Current Assets.\n\nExample:\nBus cost: ₦5,500,000\nAcc. dep after 2 yrs (₦687,500/yr): ₦1,375,000\nNBV today: ₦4,125,000"}
                  />
                </p>
                <p className="text-xl font-bold text-blue-700 mt-1">{formatCurrency(totalNBV)}</p>
                <p className="text-xs text-muted-foreground mt-0.5">As at today</p>
              </div>
              <Building2 className="h-8 w-8 text-blue-300" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5 pb-4 px-5">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1">
                  Annual Depreciation
                  <HelpTooltip
                    title="Annual Depreciation (Straight-Line)"
                    align="right"
                    content={"Estimated annual depreciation charge across all assets:\n\nFormula: (Cost − Residual Value) ÷ Useful Life\n\nExample:\n(₦5,500,000 − ₦500,000) ÷ 8 yrs = ₦625,000/yr\n\nNote: Reducing-balance assets have a variable annual charge — this figure uses straight-line for all assets as an estimate."}
                  />
                </p>
                <p className="text-xl font-bold text-orange-600 mt-1">{formatCurrency(totalAnnualDep)}</p>
                <p className="text-xs text-muted-foreground mt-0.5">Straight-line estimate</p>
              </div>
              <TrendingDown className="h-8 w-8 text-orange-300" />
            </div>
          </CardContent>
        </Card>
      </div>

      {loading && (
        <div className="text-center py-16 text-muted-foreground">Loading assets…</div>
      )}

      {!loading && assets.length === 0 && (
        <Card>
          <CardContent className="py-16 text-center">
            <Package className="h-12 w-12 mx-auto mb-3 text-muted-foreground/30" />
            <p className="text-muted-foreground">No assets recorded yet.</p>
            <p className="text-sm text-muted-foreground mt-1">Click "Add Asset" to enter school assets.</p>
          </CardContent>
        </Card>
      )}

      {/* Asset table grouped by category */}
      {!loading && Object.entries(groupedByCategory).sort(([a], [b]) => a.localeCompare(b)).map(([cat, items]) => (
        <Card key={cat}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">{cat}</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/30">
                    <th className="text-left px-4 py-2 font-medium text-muted-foreground">Asset Name</th>
                    <th className="text-left px-4 py-2 font-medium text-muted-foreground">Purchase Date</th>
                    <th className="text-right px-4 py-2 font-medium text-muted-foreground">
                      <span className="inline-flex items-center gap-1 justify-end">
                        Cost
                        <HelpTooltip align="right" content={"The original purchase price paid for the asset (historical cost). This never changes — depreciation is tracked separately."} />
                      </span>
                    </th>
                    <th className="text-right px-4 py-2 font-medium text-muted-foreground">
                      <span className="inline-flex items-center gap-1 justify-end">
                        Acc. Depreciation
                        <HelpTooltip align="right" title="Accumulated Depreciation" content={"Total depreciation charged from purchase date to today.\n\nFormula (straight-line):\nAcc. Dep = Annual Charge × Years Elapsed\n\nExample:\nAnnual charge = ₦625,000\n2.5 years elapsed\nAccumulated = ₦1,562,500\n\nShown in brackets because it reduces the asset's value."} />
                      </span>
                    </th>
                    <th className="text-right px-4 py-2 font-medium text-muted-foreground">
                      <span className="inline-flex items-center gap-1 justify-end">
                        NBV (Today)
                        <HelpTooltip align="right" title="Net Book Value" content={"NBV = Purchase Cost − Accumulated Depreciation\n\nThis is the carrying value of the asset in your books as at today. It appears in the Financial Statements balance sheet under Non-Current Assets."} />
                      </span>
                    </th>
                    <th className="text-left px-4 py-2 font-medium text-muted-foreground">Method</th>
                    <th className="text-right px-4 py-2 font-medium text-muted-foreground">
                      <span className="inline-flex items-center gap-1 justify-end">
                        Life (Yrs)
                        <HelpTooltip align="right" content={"Useful life entered when the asset was added. Determines how quickly cost is spread.\n\nShorter life = higher annual depreciation charge."} />
                      </span>
                    </th>
                    <th className="px-4 py-2 font-medium text-muted-foreground text-right sr-only">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((asset) => (
                    <tr key={asset.id} className="border-b last:border-0 hover:bg-muted/20">
                      <td className="px-4 py-2.5 font-medium">
                        {asset.name}
                        {asset.notes && (
                          <span className="block text-xs text-muted-foreground font-normal">{asset.notes}</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Calendar className="h-3 w-3" />
                          {asset.purchase_date}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{formatCurrency(asset.purchase_cost)}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-red-600">
                        ({formatCurrency(asset.accumulated_depreciation)})
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums font-semibold text-blue-700">
                        {formatCurrency(asset.net_book_value)}
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground capitalize">
                        {asset.depreciation_method === 'straight_line' ? 'Straight-Line' : 'Reducing Bal.'}
                      </td>
                      <td className="px-4 py-2.5 text-right text-muted-foreground">{asset.useful_life_years}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-1 justify-end">
                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => openEdit(asset)}>
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-red-500 hover:text-red-700" onClick={() => handleDeleteClick(asset)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {/* Category subtotal row */}
                  <tr className="bg-muted/20 font-semibold text-sm">
                    <td colSpan={2} className="px-4 py-2 text-muted-foreground">Subtotal — {cat}</td>
                    <td className="px-4 py-2 text-right tabular-nums">
                      {formatCurrency(items.reduce((s, a) => s + a.purchase_cost, 0))}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-red-600">
                      ({formatCurrency(items.reduce((s, a) => s + a.accumulated_depreciation, 0))})
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-blue-700">
                      {formatCurrency(items.reduce((s, a) => s + a.net_book_value, 0))}
                    </td>
                    <td colSpan={3} />
                  </tr>
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ))}

      {/* Add / Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingId ? 'Edit Asset' : 'Add Asset'}</DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Name */}
            <div className="space-y-1.5">
              <Label htmlFor="asset-name">Asset Name *</Label>
              <Input
                id="asset-name"
                placeholder="e.g. School Bus, Library Books"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>

            {/* Category */}
            <div className="space-y-1.5">
              <Label htmlFor="asset-cat">Category *</Label>
              <select
                id="asset-cat"
                title="Asset category"
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">Select category…</option>
                {categories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>

            {/* Purchase Date */}
            <div className="space-y-1.5">
              <Label htmlFor="asset-date">Purchase Date *</Label>
              <Input
                id="asset-date"
                type="date"
                value={form.purchase_date}
                onChange={(e) => setForm({ ...form, purchase_date: e.target.value })}
              />
            </div>

            {/* Cost + Residual value side by side */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="asset-cost">Purchase Cost (₦) *</Label>
                <Input
                  id="asset-cost"
                  type="number"
                  min={0}
                  step={0.01}
                  placeholder="0.00"
                  value={form.purchase_cost || ''}
                  onChange={(e) => setForm({ ...form, purchase_cost: parseFloat(e.target.value) || 0 })}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="asset-residual" className="flex items-center gap-1">
                  Residual Value (₦)
                  <HelpTooltip
                    title="Residual / Salvage Value"
                    content={"The estimated resale or scrap value of the asset at the end of its useful life.\n\nOnly the depreciable amount (Cost − Residual) is spread over the asset's life.\n\nExample:\nBus cost ₦5,500,000 estimated to be worth ₦500,000 after 8 yrs\n→ Depreciable amount = ₦5,000,000\n→ Annual SL charge = ₦625,000/yr\n\nIf uncertain, enter 0."}
                  />
                </Label>
                <Input
                  id="asset-residual"
                  type="number"
                  min={0}
                  step={0.01}
                  placeholder="0.00"
                  value={form.residual_value || ''}
                  onChange={(e) => setForm({ ...form, residual_value: parseFloat(e.target.value) || 0 })}
                />
              </div>
            </div>

            {/* Useful Life + Method side by side */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="asset-life" className="flex items-center gap-1">
                  Useful Life (Years) *
                  <HelpTooltip
                    title="Useful Life"
                    content={"How many years the asset is expected to remain in productive use.\n\nTypical school guidance:\n· Land & Buildings: 20–50 yrs\n· Motor Vehicles: 4–8 yrs\n· Furniture & Fittings: 5–10 yrs\n· Computer Equipment: 3–5 yrs\n· Library Books: 5–10 yrs\n· Plant & Equipment: 5–15 yrs"}
                  />
                </Label>
                <Input
                  id="asset-life"
                  type="number"
                  min={0.5}
                  step={0.5}
                  placeholder="5"
                  value={form.useful_life_years || ''}
                  onChange={(e) => setForm({ ...form, useful_life_years: parseFloat(e.target.value) || 5 })}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="asset-method" className="flex items-center gap-1">
                  Depreciation Method
                  <HelpTooltip
                    title="Depreciation Method"
                    align="right"
                    content={"Straight-Line (recommended for schools):\nEqual charge each year.\nFormula: (Cost − Residual) ÷ Life\nExample: ₦5,000,000 ÷ 8 yrs = ₦625,000/yr every year.\n\nReducing Balance:\nCharge is a % of the remaining book value — higher in early years, lower later.\nExample at 12.5%:\nYear 1: ₦687,500\nYear 2: ₦601,563\nYear 3: ₦526,367…"}
                  />
                </Label>
                <select
                  id="asset-method"
                  title="Depreciation method"
                  value={form.depreciation_method}
                  onChange={(e) =>
                    setForm({ ...form, depreciation_method: e.target.value as 'straight_line' | 'reducing_balance' })
                  }
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  {DEPRECIATION_METHODS.map((m) => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Depreciation preview */}
            {previewAnnualDep > 0 && form.depreciation_method === 'straight_line' && (
              <div className="rounded-md bg-blue-50 border border-blue-200 px-3 py-2 text-xs text-blue-800">
                Annual depreciation charge: <span className="font-semibold">{formatCurrency(previewAnnualDep)}</span>
                {' '}/ year &nbsp;·&nbsp; Monthly: <span className="font-semibold">{formatCurrency(previewAnnualDep / 12)}</span>
              </div>
            )}

            {/* Notes */}
            <div className="space-y-1.5">
              <Label htmlFor="asset-notes">Notes (optional)</Label>
              <Input
                id="asset-notes"
                placeholder="e.g. Reg. No, Serial No, location…"
                value={form.notes ?? ''}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
              />
            </div>

            {formError && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{formError}</p>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={saving}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : editingId ? 'Update Asset' : 'Add Asset'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <ConfirmDialog
        open={confirmOpen}
        title="Delete Asset"
        description={`Delete "${deleteTarget?.name}"? This cannot be undone and will affect depreciation in Financial Statements.`}
        confirmLabel={deleting ? 'Deleting…' : 'Delete'}
        onConfirm={handleDelete}
        onCancel={() => { setConfirmOpen(false); setDeleteTarget(null); }}
      />
    </div>
  );
}
