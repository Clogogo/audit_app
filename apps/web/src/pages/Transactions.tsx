import { useEffect, useRef, useState } from 'react';
import {
  Plus, Trash2, Pencil, Building2, Tag, ChevronDown, X,
  Receipt, SlidersHorizontal, ChevronLeft, ChevronRight, Search,
} from 'lucide-react';
import { getTransactions, getSummary, getTransactionYears, createTransaction, updateTransaction, deleteTransaction, batchUpdateCategory, getTerms } from '../api/client';
import type { Transaction, TransactionCreate, TransactionSummary, Term } from '../api/types';
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '../api/types';
import { Button } from '../components/ui/button';
import { TypeBadge, CategoryBadge } from '../components/CategoryBadge';
import { TransactionForm } from '../components/TransactionForm';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { TermSelect } from '../components/TermSelect';
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
  const [categorySearch, setCategorySearch] = useState('');
  const categoryDropdownRef = useRef<HTMLDivElement>(null);
  const [filterBank, setFilterBank] = useState('');
  const [filterYear, setFilterYear] = useState(String(new Date().getFullYear()));
  const [filterMonth, setFilterMonth] = useState('all');
  const [filterVendor, setFilterVendor] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [terms, setTerms] = useState<Term[]>([]);
  const [selectedTermId, setSelectedTermId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [batchCategory, setBatchCategory] = useState('');
  const [batchCategoryApplying, setBatchCategoryApplying] = useState(false);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [summaryData, setSummaryData] = useState<TransactionSummary | null>(null);
  const filterDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const PAGE_SIZE = 100;
  const [yearOptions, setYearOptions] = useState<string[]>([String(new Date().getFullYear())]);

  useEffect(() => {
    getTransactionYears().then((years) => {
      if (years.length > 0) setYearOptions(years.map(String));
    }).catch(() => {/* keep default */});
  }, []);

  useEffect(() => { getTerms().then(setTerms); }, []);

  const handleSelectTerm = (term: Term | null) => {
    setSelectedTermId(term?.id ?? null);
    if (term) {
      setFilterYear('all');
      setFilterMonth('all');
      setStartDate(term.start_date);
      setEndDate(term.end_date);
    }
  };

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

  const load = (pageOverride?: number, preserveScroll = false) => {
    const pg = pageOverride ?? page;
    const scrollPosition = preserveScroll ? window.scrollY : 0;
    const dates = _apiDates();
    setLoading(true);
    setSelected(new Set());

    const txPromise = getTransactions({
      type: filterType !== 'all' ? filterType : undefined,
      category: filterCategories.length > 0 ? filterCategories.join(',') : undefined,
      ...dates,
      bank: filterBank || undefined,
      vendor: filterVendor || undefined,
      limit: PAGE_SIZE,
      offset: pg * PAGE_SIZE,
    }).then((result) => {
      setTransactions(result.items);
      setTotal(result.total);
    });

    // Fetch accurate totals across ALL pages (not just current page).
    // Summary always covers all types regardless of the type filter in the list.
    const summaryPromise = (pg === 0)
      ? getSummary({
          ...dates,
          bank: filterBank || undefined,
          vendor: filterVendor || undefined,
        }).then(setSummaryData)
      : Promise.resolve();

    Promise.all([txPromise, summaryPromise]).finally(() => {
      setLoading(false);
      if (preserveScroll) setTimeout(() => window.scrollTo(0, scrollPosition), 0);
    });
  };

  useEffect(() => {
    if (filterDebounceRef.current) clearTimeout(filterDebounceRef.current);
    filterDebounceRef.current = setTimeout(() => {
      setPage(0);
      load(0);
    }, 250);
    return () => { if (filterDebounceRef.current) clearTimeout(filterDebounceRef.current); };
  }, [filterType, filterCategories, filterYear, filterMonth, startDate, endDate, filterBank, filterVendor]);

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
      load(undefined, true); // Preserve scroll position after edit
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
      load(undefined, true); // Preserve scroll position after delete
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

  const monthOptions = [
    { value: '1',  label: 'January' },  { value: '2',  label: 'February' },
    { value: '3',  label: 'March' },    { value: '4',  label: 'April' },
    { value: '5',  label: 'May' },      { value: '6',  label: 'June' },
    { value: '7',  label: 'July' },     { value: '8',  label: 'August' },
    { value: '9',  label: 'September' },{ value: '10', label: 'October' },
    { value: '11', label: 'November' }, { value: '12', label: 'December' },
  ];

  const visible = transactions;

  const allSelected = visible.length > 0 && visible.every((t) => selected.has(t.id));
  const someSelected = visible.some((t) => selected.has(t.id));

  // Use server-computed totals so the strip is accurate across all pages,
  // not just the current 100-row subset.
  const stripIncome = summaryData?.total_income ?? 0;
  const stripExpense = summaryData?.total_expenses ?? 0;
  const net = stripIncome - stripExpense;

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
      load(undefined, true); // Preserve scroll position after batch update
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

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Transactions</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {loading ? 'Loading…' : `${total.toLocaleString()} transaction${total !== 1 ? 's' : ''}${hasFilters ? ' · filtered' : ''}`}
          </p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={(open) => { setDialogOpen(open); if (!open) setSaveError(null); }}>
          <DialogTrigger asChild>
            <Button onClick={openAdd} className="gap-1.5 shadow-sm">
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

      {/* ── Summary strip ──────────────────────────────────────────────────── */}
      <div className="flex items-center flex-wrap gap-x-6 gap-y-2 rounded-xl border bg-muted/30 px-4 py-2.5 text-sm">
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-green-500" />
          <span className="text-muted-foreground">Income</span>
          <span className="font-semibold text-green-600 tabular-nums">+{formatCurrency(stripIncome, 'NGN')}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-red-500" />
          <span className="text-muted-foreground">Expense</span>
          <span className="font-semibold text-red-600 tabular-nums">-{formatCurrency(stripExpense, 'NGN')}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-blue-500" />
          <span className="text-muted-foreground">Net</span>
          <span className={`font-semibold tabular-nums ${net >= 0 ? 'text-green-600' : 'text-red-600'}`}>{formatCurrency(net, 'NGN')}</span>
        </div>
      </div>

      {/* ── Filters ────────────────────────────────────────────────────────── */}
      <div className="rounded-2xl border bg-card p-4 shadow-sm space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
            <SlidersHorizontal className="h-4 w-4" />
            Filters
          </div>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters} className="h-7 text-xs gap-1">
              <X className="h-3.5 w-3.5" /> Clear all
            </Button>
          )}
        </div>
        <div className="flex gap-2.5 flex-wrap">
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
              onClick={() => { setCategoryDropdownOpen((o) => { if (o) setCategorySearch(''); return !o; }); }}
              className="flex items-center gap-1.5 h-10 px-3 rounded-md border border-input bg-background text-sm min-w-44 text-left hover:bg-accent transition-colors"
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
              <div className="absolute top-full mt-1 left-0 z-50 w-56 rounded-md border bg-popover shadow-md flex flex-col max-h-80">
                {/* Search box */}
                <div className="p-2 border-b shrink-0">
                  <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-muted/60 border border-input">
                    <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <input
                      autoFocus
                      type="text"
                      placeholder="Search categories…"
                      value={categorySearch}
                      onChange={(e) => setCategorySearch(e.target.value)}
                      className="flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                    />
                    {categorySearch && (
                      <X
                        className="h-3 w-3 text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
                        onClick={() => setCategorySearch('')}
                      />
                    )}
                  </div>
                </div>

                {/* Category list */}
                <div className="overflow-y-auto p-1">
                  {(() => {
                    const q = categorySearch.toLowerCase();
                    const expFiltered = EXPENSE_CATEGORIES.filter((c) => c.toLowerCase().includes(q));
                    const incFiltered = INCOME_CATEGORIES.filter((c) => !EXPENSE_CATEGORIES.includes(c) && c.toLowerCase().includes(q));
                    const noResults = expFiltered.length === 0 && incFiltered.length === 0;

                    if (noResults) {
                      return <p className="text-xs text-muted-foreground text-center py-4">No categories found</p>;
                    }

                    return (
                      <>
                        {expFiltered.length > 0 && (
                          <>
                            <p className="px-2 py-1 text-xs font-semibold text-muted-foreground">Expense</p>
                            {expFiltered.map((cat) => (
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
                          </>
                        )}
                        {incFiltered.length > 0 && (
                          <>
                            <p className="px-2 py-1 mt-1 text-xs font-semibold text-muted-foreground">Income</p>
                            {incFiltered.map((cat) => (
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
                          </>
                        )}
                      </>
                    );
                  })()}
                </div>
              </div>
            )}
          </div>
          <Input
            className="w-40"
            placeholder="Filter by bank"
            value={filterBank}
            onChange={(e) => setFilterBank(e.target.value)}
          />
          {/* Year filter */}
          <Select value={filterYear} onValueChange={(v) => { setFilterYear(v); setStartDate(''); setEndDate(''); setSelectedTermId(null); }}>
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
          <Select value={filterMonth} onValueChange={(v) => { setFilterMonth(v); setStartDate(''); setEndDate(''); setSelectedTermId(null); }}>
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
          {/* Term filter */}
          <TermSelect
            terms={terms}
            selectedTermId={selectedTermId}
            onSelectTerm={handleSelectTerm}
          />
          {/* Custom date range (visible only when no year/month picker is active) */}
          {filterYear === 'all' && filterMonth === 'all' && (
            <>
              <Input type="date" className="w-40" value={startDate} onChange={(e) => { setStartDate(e.target.value); setSelectedTermId(null); }} />
              <Input type="date" className="w-40" value={endDate} onChange={(e) => { setEndDate(e.target.value); setSelectedTermId(null); }} />
            </>
          )}
          {/* Vendor / customer filter */}
          <Input
            className="w-44"
            placeholder="Filter by customer"
            value={filterVendor}
            onChange={(e) => setFilterVendor(e.target.value)}
          />
        </div>
      </div>

      {/* ── Batch action bar ───────────────────────────────────────────────── */}
      {selected.size > 0 && (
        <div className="flex items-center gap-2 flex-wrap rounded-2xl border border-primary/20 bg-primary/5 px-4 py-2.5 shadow-sm">
          <span className="text-sm font-medium text-foreground">{selected.size} selected</span>
          <div className="h-4 w-px bg-border mx-1" />
          <Select value={batchCategory} onValueChange={setBatchCategory}>
            <SelectTrigger className="w-44 h-8 text-xs bg-background">
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
            className="h-8 text-xs bg-background gap-1"
          >
            <Tag className="h-3.5 w-3.5" />
            {batchCategoryApplying ? 'Applying…' : `Apply to ${selected.size}`}
          </Button>
          <Button variant="destructive" size="sm" onClick={askBatchDelete} disabled={deleting} className="h-8 text-xs gap-1 ml-auto">
            <Trash2 className="h-3.5 w-3.5" />
            Delete
          </Button>
        </div>
      )}

      {/* ── Table ──────────────────────────────────────────────────────────── */}
      {loading ? (
        <div className="rounded-2xl border bg-card overflow-hidden shadow-sm">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-4 border-b last:border-0">
              <div className="h-4 w-4 rounded bg-muted animate-pulse" />
              <div className="h-4 w-20 rounded bg-muted animate-pulse" />
              <div className="h-5 w-16 rounded-full bg-muted animate-pulse" />
              <div className="h-4 flex-1 rounded bg-muted animate-pulse" />
              <div className="h-5 w-20 rounded-full bg-muted animate-pulse" />
              <div className="h-4 w-24 rounded bg-muted animate-pulse" />
            </div>
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="rounded-2xl border bg-card flex flex-col items-center justify-center py-20 text-center shadow-sm">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted mb-4">
            <Receipt className="h-7 w-7 text-muted-foreground/50" />
          </div>
          <p className="text-base font-semibold">No transactions found</p>
          <p className="text-sm text-muted-foreground mt-1 max-w-sm">
            {hasFilters ? 'Try adjusting or clearing your filters.' : 'Add a transaction or import a bank statement to get started.'}
          </p>
          {hasFilters
            ? <Button variant="outline" size="sm" onClick={clearFilters} className="mt-4 gap-1"><X className="h-3.5 w-3.5" /> Clear filters</Button>
            : <Button size="sm" onClick={openAdd} className="mt-4 gap-1.5"><Plus className="h-4 w-4" /> Add Transaction</Button>}
        </div>
      ) : (
        <div className="rounded-2xl border bg-card overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[760px]">
              <thead className="sticky top-0 z-10 bg-muted/60 backdrop-blur supports-[backdrop-filter]:bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-3 w-10" aria-label="Select all">
                    <input
                      type="checkbox"
                      title="Select all"
                      checked={allSelected}
                      ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected; }}
                      onChange={toggleAll}
                      className="h-4 w-4 rounded border-gray-300 cursor-pointer align-middle"
                    />
                  </th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wide text-muted-foreground">Date</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wide text-muted-foreground">Type</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wide text-muted-foreground">Description</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wide text-muted-foreground">Category</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wide text-muted-foreground">Vendor</th>
                  <th className="text-left px-4 py-3 font-semibold text-xs uppercase tracking-wide text-muted-foreground">Bank</th>
                  <th className="text-right px-4 py-3 font-semibold text-xs uppercase tracking-wide text-muted-foreground">Amount</th>
                  <th className="px-4 py-3 w-20"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {visible.map((tx) => (
                  <tr
                    key={tx.id}
                    className={`group transition-colors ${selected.has(tx.id) ? 'bg-primary/5' : 'hover:bg-muted/40'}`}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        title={`Select transaction ${tx.id}`}
                        checked={selected.has(tx.id)}
                        onChange={() => toggleOne(tx.id)}
                        className="h-4 w-4 rounded border-gray-300 cursor-pointer align-middle"
                      />
                    </td>
                    <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">{formatDate(tx.date)}</td>
                    <td className="px-4 py-3"><TypeBadge type={tx.type} /></td>
                    <td className="px-4 py-3 font-medium max-w-md">
                      <span className="line-clamp-2">{tx.description}</span>
                    </td>
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
                    <td className={`px-4 py-3 text-right font-semibold tabular-nums whitespace-nowrap ${tx.type === 'income' ? 'text-green-600' : tx.type === 'transfer' ? 'text-muted-foreground' : 'text-red-600'}`}>
                      {tx.type === 'income' ? '+' : tx.type === 'expense' ? '-' : ''}{formatCurrency(tx.amount, tx.currency ?? 'NGN')}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-0.5 justify-end opacity-60 group-hover:opacity-100 transition-opacity">
                        <Button variant="ghost" size="icon" onClick={() => openEdit(tx)} className="h-8 w-8" aria-label="Edit">
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => askDelete(tx.id)} className="h-8 w-8" aria-label="Delete">
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Pagination ─────────────────────────────────────────────────────── */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between gap-4 text-sm text-muted-foreground">
          <span>
            Showing {(page * PAGE_SIZE + 1).toLocaleString()}–{Math.min((page + 1) * PAGE_SIZE, total).toLocaleString()} of {total.toLocaleString()}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0 || loading}
              onClick={() => { const p = page - 1; setPage(p); load(p); }}
              className="h-8 w-8 p-0"
              aria-label="Previous page"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="px-2 tabular-nums">Page {page + 1} of {Math.ceil(total / PAGE_SIZE)}</span>
            <Button
              variant="outline"
              size="sm"
              disabled={(page + 1) * PAGE_SIZE >= total || loading}
              onClick={() => { const p = page + 1; setPage(p); load(p); }}
              className="h-8 w-8 p-0"
              aria-label="Next page"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
