import { useEffect, useRef, useState } from 'react';
import { Plus, Trash2, Pencil, Building2, Tag, ChevronDown, X } from 'lucide-react';
import { getTransactions, createTransaction, updateTransaction, deleteTransaction, batchUpdateCategory } from '../api/client';
import type { Transaction, TransactionCreate } from '../api/types';
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '../api/types';
import { Button } from '../components/ui/button';
import { TypeBadge, CategoryBadge } from '../components/CategoryBadge';
import { TransactionForm } from '../components/TransactionForm';
import { ConfirmDialog } from '../components/ConfirmDialog';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../components/ui/dialog';
import { formatCurrency, formatDate } from '../lib/utils';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';

export function Transactions() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Transaction | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [filterType, setFilterType] = useState('all');
  const [filterCategories, setFilterCategories] = useState<string[]>([]);
  const [categoryDropdownOpen, setCategoryDropdownOpen] = useState(false);
  const categoryDropdownRef = useRef<HTMLDivElement>(null);
  const [filterBank, setFilterBank] = useState('');
  const [filterYear, setFilterYear] = useState('all');
  const [filterMonth, setFilterMonth] = useState('all');
  const [filterVendor, setFilterVendor] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [batchCategory, setBatchCategory] = useState('');
  const [batchCategoryApplying, setBatchCategoryApplying] = useState(false);

  // Confirm dialog state
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState<'single' | 'batch'>('single');
  const [confirmId, setConfirmId] = useState<number | null>(null);

  // Derive API date range from year/month pickers or manual date inputs
  const _apiDates = (): { start_date?: string; end_date?: string } => {
    if (filterYear !== 'all' || filterMonth !== 'all') {
      const y = filterYear !== 'all' ? parseInt(filterYear) : new Date().getFullYear();
      if (filterMonth !== 'all') {
        const m = parseInt(filterMonth);
        const last = new Date(y, m, 0).getDate(); // last day of month
        return {
          start_date: `${y}-${String(m).padStart(2, '0')}-01`,
          end_date:   `${y}-${String(m).padStart(2, '0')}-${String(last).padStart(2, '0')}`,
        };
      }
      return { start_date: `${y}-01-01`, end_date: `${y}-12-31` };
    }
    return { start_date: startDate || undefined, end_date: endDate || undefined };
  };

  const load = () => {
    setLoading(true);
    setSelected(new Set());
    getTransactions({
      type: filterType !== 'all' ? filterType : undefined,
      ..._apiDates(),
    })
      .then(setTransactions)
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [filterType, filterYear, filterMonth, startDate, endDate]);

  const handleSubmit = async (rawData: TransactionCreate) => {
    setSaving(true);
    setSaveError(null);
    // Strip extra Transaction fields (id, created_at, updated_at, etc.) that
    // react-hook-form picks up from defaultValues when editing.
    const data: TransactionCreate = {
      type: rawData.type,
      amount: rawData.amount,
      currency: rawData.currency ?? 'NGN',
      category: rawData.category,
      description: rawData.description,
      date: rawData.date,
      vendor: rawData.vendor || undefined,
      bank: rawData.bank || undefined,
      file_id: rawData.file_id ?? undefined,
    };
    try {
      if (editTarget) {
        await updateTransaction(editTarget.id, data);
      } else {
        await createTransaction(data);
      }
      setDialogOpen(false);
      setEditTarget(null);
      load();
    } catch (err: unknown) {
      const res = (err as { response?: { data?: unknown; status?: number } })?.response;
      const body = res?.data;
      let msg = `Error ${res?.status ?? '?'}: `;
      if (typeof body === 'string') {
        msg += body;
      } else if (body && typeof body === 'object') {
        const detail = (body as { detail?: unknown }).detail;
        if (typeof detail === 'string') {
          msg += detail;
        } else if (Array.isArray(detail)) {
          msg += detail.map((d: { msg?: string; loc?: unknown[] }) => {
            const loc = (d.loc ?? []).filter((l) => l !== 'body').join('.');
            return loc ? `${loc}: ${d.msg}` : d.msg ?? JSON.stringify(d);
          }).join('; ');
        } else {
          msg += JSON.stringify(body);
        }
      } else {
        msg = 'Failed to save transaction. Please try again.';
      }
      setSaveError(msg);
      console.error('Save transaction error:', err);
    } finally {
      setSaving(false);
    }
  };

  const askDelete = (id: number) => {
    setConfirmTarget('single');
    setConfirmId(id);
    setConfirmOpen(true);
  };

  const askBatchDelete = () => {
    setConfirmTarget('batch');
    setConfirmId(null);
    setConfirmOpen(true);
  };

  const handleConfirmed = async () => {
    setDeleting(true);
    try {
      if (confirmTarget === 'batch') {
        await Promise.all([...selected].map((id) => deleteTransaction(id)));
      } else if (confirmId !== null) {
        await deleteTransaction(confirmId);
      }
    } finally {
      setDeleting(false);
      setConfirmOpen(false);
      setConfirmId(null);
      load();
    }
  };

  const openEdit = (tx: Transaction) => {
    setEditTarget(tx);
    setDialogOpen(true);
  };

  const openAdd = () => {
    setEditTarget(null);
    setDialogOpen(true);
  };

  const hasFilters = filterType !== 'all' || filterCategories.length > 0 || startDate || endDate
    || filterBank || filterYear !== 'all' || filterMonth !== 'all' || filterVendor;
  const clearFilters = () => {
    setFilterType('all');
    setFilterCategories([]);
    setFilterBank('');
    setFilterYear('all');
    setFilterMonth('all');
    setFilterVendor('');
    setStartDate('');
    setEndDate('');
  };

  // Close category dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (categoryDropdownRef.current && !categoryDropdownRef.current.contains(e.target as Node)) {
        setCategoryDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const toggleCategory = (cat: string) => {
    setFilterCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  };

  const currentYear = new Date().getFullYear();
  const yearOptions = Array.from({ length: 5 }, (_, i) => String(currentYear - i));
  const monthOptions = [
    { value: '1',  label: 'January' },  { value: '2',  label: 'February' },
    { value: '3',  label: 'March' },    { value: '4',  label: 'April' },
    { value: '5',  label: 'May' },      { value: '6',  label: 'June' },
    { value: '7',  label: 'July' },     { value: '8',  label: 'August' },
    { value: '9',  label: 'September' },{ value: '10', label: 'October' },
    { value: '11', label: 'November' }, { value: '12', label: 'December' },
  ];

  const bankNames = [...new Set(transactions.map((t) => t.bank).filter(Boolean) as string[])].sort();

  const visible = transactions
    .filter((t) => !filterBank || t.bank === filterBank)
    .filter((t) => filterCategories.length === 0 || filterCategories.includes(t.category))
    .filter((t) => !filterVendor || (t.vendor ?? '').toLowerCase().includes(filterVendor.toLowerCase()));

  const allSelected = visible.length > 0 && visible.every((t) => selected.has(t.id));
  const someSelected = visible.some((t) => selected.has(t.id));

  const toggleAll = () => {
    if (allSelected) {
      setSelected((prev) => {
        const next = new Set(prev);
        visible.forEach((t) => next.delete(t.id));
        return next;
      });
    } else {
      setSelected((prev) => {
        const next = new Set(prev);
        visible.forEach((t) => next.add(t.id));
        return next;
      });
    }
  };

  const handleBatchCategory = async () => {
    if (!batchCategory || selected.size === 0) return;
    setBatchCategoryApplying(true);
    try {
      await batchUpdateCategory([...selected], batchCategory);
      setBatchCategory('');
      setSelected(new Set());
      load();
    } finally {
      setBatchCategoryApplying(false);
    }
  };

  const toggleOne = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const confirmDescription =
    confirmTarget === 'batch'
      ? `This will permanently delete ${selected.size} transaction${selected.size > 1 ? 's' : ''}. This action cannot be undone.`
      : 'This will permanently delete the transaction. This action cannot be undone.';

  return (
    <div className="space-y-6">
      <ConfirmDialog
        open={confirmOpen}
        title={confirmTarget === 'batch' ? `Delete ${selected.size} transaction${selected.size > 1 ? 's' : ''}?` : 'Delete transaction?'}
        description={confirmDescription}
        confirmLabel="Delete"
        loading={deleting}
        onConfirm={handleConfirmed}
        onCancel={() => setConfirmOpen(false)}
      />

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Transactions</h1>
        <div className="flex items-center gap-2">
          {selected.size > 0 && (
            <>
              <span className="text-sm text-muted-foreground">{selected.size} selected</span>
              <Select value={batchCategory} onValueChange={setBatchCategory}>
                <SelectTrigger className="w-44 h-8 text-xs">
                  <SelectValue placeholder="Set category…" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="_header_expense" disabled className="text-xs font-semibold text-muted-foreground">— Expense —</SelectItem>
                  {EXPENSE_CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  <SelectItem value="_header_income" disabled className="text-xs font-semibold text-muted-foreground">— Income —</SelectItem>
                  {INCOME_CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                </SelectContent>
              </Select>
              <Button
                size="sm"
                variant="outline"
                disabled={!batchCategory || batchCategoryApplying}
                onClick={handleBatchCategory}
                className="h-8 text-xs"
              >
                <Tag className="h-3.5 w-3.5" />
                {batchCategoryApplying ? 'Applying…' : `Apply to ${selected.size}`}
              </Button>
              <Button variant="destructive" size="sm" onClick={askBatchDelete} disabled={deleting} className="h-8 text-xs">
                <Trash2 className="h-3.5 w-3.5" />
                Delete
              </Button>
            </>
          )}
          <Dialog open={dialogOpen} onOpenChange={(open) => { setDialogOpen(open); if (!open) setSaveError(null); }}>
            <DialogTrigger asChild>
              <Button onClick={openAdd}>
                <Plus className="h-4 w-4" />
                Add Transaction
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle>{editTarget ? 'Edit Transaction' : 'New Transaction'}</DialogTitle>
              </DialogHeader>
              {saveError && (
                <p className="text-sm text-destructive bg-destructive/10 rounded px-3 py-2">{saveError}</p>
              )}
              <TransactionForm
                defaultValues={editTarget ?? undefined}
                onSubmit={handleSubmit}
                onCancel={() => setDialogOpen(false)}
                isLoading={saving}
              />
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <Select value={filterType} onValueChange={setFilterType}>
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="income">Income</SelectItem>
            <SelectItem value="expense">Expense</SelectItem>
            <SelectItem value="transfer">Transfer</SelectItem>
          </SelectContent>
        </Select>
        {/* Multi-select category filter */}
        <div ref={categoryDropdownRef} className="relative">
          <button
            type="button"
            onClick={() => setCategoryDropdownOpen((o) => !o)}
            className="flex items-center gap-1.5 h-10 px-3 rounded-md border border-input bg-background text-sm min-w-44 text-left hover:bg-accent"
          >
            <span className="flex-1 truncate text-muted-foreground">
              {filterCategories.length === 0
                ? 'All Categories'
                : filterCategories.length === 1
                  ? filterCategories[0]
                  : `${filterCategories.length} categories`}
            </span>
            {filterCategories.length > 0 && (
              <X
                className="h-3.5 w-3.5 shrink-0 text-muted-foreground hover:text-foreground"
                onClick={(e) => { e.stopPropagation(); setFilterCategories([]); }}
              />
            )}
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          </button>
          {categoryDropdownOpen && (
            <div className="absolute top-full mt-1 left-0 z-50 w-52 rounded-md border bg-popover shadow-md max-h-72 overflow-y-auto">
              <div className="p-1">
                <p className="px-2 py-1 text-xs font-semibold text-muted-foreground">Expense</p>
                {EXPENSE_CATEGORIES.map((cat) => (
                  <label key={cat} className="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer text-sm hover:bg-accent">
                    <input
                      type="checkbox"
                      checked={filterCategories.includes(cat)}
                      onChange={() => toggleCategory(cat)}
                      className="h-3.5 w-3.5 rounded"
                    />
                    {cat}
                  </label>
                ))}
                <p className="px-2 py-1 mt-1 text-xs font-semibold text-muted-foreground">Income</p>
                {INCOME_CATEGORIES.filter((c) => !EXPENSE_CATEGORIES.includes(c)).map((cat) => (
                  <label key={cat} className="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer text-sm hover:bg-accent">
                    <input
                      type="checkbox"
                      checked={filterCategories.includes(cat)}
                      onChange={() => toggleCategory(cat)}
                      className="h-3.5 w-3.5 rounded"
                    />
                    {cat}
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
        {bankNames.length > 0 && (
          <Select value={filterBank || 'all'} onValueChange={(v) => setFilterBank(v === 'all' ? '' : v)}>
            <SelectTrigger className="w-44">
              <SelectValue placeholder="All Banks" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Banks</SelectItem>
              {bankNames.map((b) => (
                <SelectItem key={b} value={b}>{b}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {/* Year filter */}
        <Select value={filterYear} onValueChange={(v) => { setFilterYear(v); setStartDate(''); setEndDate(''); }}>
          <SelectTrigger className="w-28">
            <SelectValue placeholder="Year" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Years</SelectItem>
            {yearOptions.map((y) => (
              <SelectItem key={y} value={y}>{y}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {/* Month filter */}
        <Select value={filterMonth} onValueChange={(v) => { setFilterMonth(v); setStartDate(''); setEndDate(''); }}>
          <SelectTrigger className="w-32">
            <SelectValue placeholder="Month" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Months</SelectItem>
            {monthOptions.map((m) => (
              <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {/* Custom date range (visible only when no year/month picker is active) */}
        {filterYear === 'all' && filterMonth === 'all' && (
          <>
            <Input type="date" className="w-40" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            <Input type="date" className="w-40" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </>
        )}
        {/* Vendor / customer filter */}
        <Input
          className="w-44"
          placeholder="Filter by customer"
          value={filterVendor}
          onChange={(e) => setFilterVendor(e.target.value)}
        />
        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            Clear
          </Button>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-center py-16 text-muted-foreground">Loading...</div>
      ) : visible.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">No transactions found</div>
      ) : (
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-4 py-3 w-10" aria-label="Select all">
                  <input
                    type="checkbox"
                    title="Select all"
                    checked={allSelected}
                    ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected; }}
                    onChange={toggleAll}
                    className="h-4 w-4 rounded border-gray-300 cursor-pointer"
                  />
                </th>
                <th className="text-left px-4 py-3 font-medium">Date</th>
                <th className="text-left px-4 py-3 font-medium">Type</th>
                <th className="text-left px-4 py-3 font-medium">Description</th>
                <th className="text-left px-4 py-3 font-medium">Category</th>
                <th className="text-left px-4 py-3 font-medium">Vendor</th>
                <th className="text-left px-4 py-3 font-medium">Bank</th>
                <th className="text-right px-4 py-3 font-medium">Amount</th>
                <th className="px-4 py-3"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {visible.map((tx) => (
                <tr
                  key={tx.id}
                  className={`hover:bg-muted/30 transition-colors ${selected.has(tx.id) ? 'bg-muted/20' : ''}`}
                >
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      title={`Select transaction ${tx.id}`}
                      checked={selected.has(tx.id)}
                      onChange={() => toggleOne(tx.id)}
                      className="h-4 w-4 rounded border-gray-300 cursor-pointer"
                    />
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{formatDate(tx.date)}</td>
                  <td className="px-4 py-3"><TypeBadge type={tx.type} /></td>
                  <td className="px-4 py-3 font-medium">{tx.description}</td>
                  <td className="px-4 py-3"><CategoryBadge category={tx.category} type={tx.type} /></td>
                  <td className="px-4 py-3 text-muted-foreground">{tx.vendor || '—'}</td>
                  <td className="px-4 py-3">
                    {tx.bank ? (
                      <Badge variant="outline" className="gap-1 text-xs font-normal">
                        <Building2 className="h-3 w-3" />
                        {tx.bank}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className={`px-4 py-3 text-right font-semibold ${tx.type === 'income' ? 'text-green-600' : 'text-red-600'}`}>
                    {tx.type === 'income' ? '+' : '-'}{formatCurrency(tx.amount, tx.currency ?? 'NGN')}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1 justify-end">
                      <Button variant="ghost" size="icon" onClick={() => openEdit(tx)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => askDelete(tx.id)}>
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
