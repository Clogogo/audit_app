import { useEffect, useState, useCallback, useRef } from 'react';
import {
  Download,
  FileSpreadsheet,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Calculator,
  CalendarRange,
} from 'lucide-react';
import { getTaxSummary, getTaxYears, exportCITExcel } from '../api/client';
import type { TaxSummary } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { formatCurrency } from '../lib/utils';
import { HelpTooltip } from '../components/HelpTooltip';

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function todayStr() { return new Date().toISOString().slice(0, 10); }
function yearStart(y: number) { return `${y}-01-01`; }
function yearEnd(y: number)   { return `${y}-12-31`; }

type Preset = 'full_year' | 'ytd' | 'q1' | 'q2' | 'q3' | 'q4' | 'custom';

function buildPresets(year: number): Record<Exclude<Preset, 'custom'>, { label: string; start: string; end: string }> {
  const isCurrentYear = year === new Date().getFullYear();
  return {
    full_year: { label: 'Full Year', start: yearStart(year), end: yearEnd(year) },
    ytd:       { label: 'Year to Date', start: yearStart(year), end: isCurrentYear ? todayStr() : yearEnd(year) },
    q1:        { label: 'Q1 (Jan–Mar)', start: `${year}-01-01`, end: `${year}-03-31` },
    q2:        { label: 'Q2 (Apr–Jun)', start: `${year}-04-01`, end: `${year}-06-30` },
    q3:        { label: 'Q3 (Jul–Sep)', start: `${year}-07-01`, end: `${year}-09-30` },
    q4:        { label: 'Q4 (Oct–Dec)', start: `${year}-10-01`, end: `${year}-12-31` },
  };
}

function SectionRow({
  label, amount, indent = false, bold = false, positive, muted = false, help,
}: {
  label: string; amount: number; indent?: boolean; bold?: boolean; positive?: boolean; muted?: boolean; help?: string;
}) {
  const colorClass =
    positive === undefined || muted ? 'text-foreground'
    : positive ? 'text-income'
    : 'text-expense';
  return (
    <div className={`flex items-center justify-between py-1.5 border-b border-border/40 last:border-0 ${indent ? 'pl-6' : ''} ${muted ? 'text-muted-foreground' : ''}`}>
      <span className={`flex items-center gap-1.5 ${bold ? 'font-semibold text-sm' : 'text-sm'}`}>
        {label}
        {help && <HelpTooltip content={help} align="left" />}
      </span>
      <span className={`tabular-nums text-sm font-medium ${colorClass} ${bold ? 'font-semibold' : ''}`}>
        {formatCurrency(amount)}
      </span>
    </div>
  );
}

function CollapsibleSection({ title, total, items, colorClass = '', defaultOpen = false }: {
  title: string; total: number; items: Record<string, number>; colorClass?: string; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const sorted = Object.entries(items).sort((a, b) => b[1] - a[1]);
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-muted/30 hover:bg-muted/50 transition-colors"
      >
        <span className="font-medium text-sm">{title}</span>
        <div className="flex items-center gap-3">
          <span className={`tabular-nums text-sm font-semibold ${colorClass}`}>{formatCurrency(total)}</span>
          {open ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
        </div>
      </button>
      {open && sorted.length > 0 && (
        <div className="px-4 py-2 divide-y divide-border/40">
          {sorted.map(([label, amount]) => (
            <div key={label} className="flex items-center justify-between py-1.5 text-sm">
              <span className="text-muted-foreground">{label}</span>
              <span className="tabular-nums font-medium">{formatCurrency(amount)}</span>
            </div>
          ))}
        </div>
      )}
      {open && sorted.length === 0 && (
        <div className="px-4 py-3 text-sm text-muted-foreground italic">No entries</div>
      )}
    </div>
  );
}

function NumericInput({
  value,
  onChange,
  className,
  placeholder = '0',
  title,
}: {
  value: number;
  onChange: (n: number) => void;
  className?: string;
  placeholder?: string;
  title?: string;
}) {
  const [focused, setFocused] = useState(false);
  const [raw, setRaw] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const display = focused ? raw : (value === 0 ? '' : value.toLocaleString('en-NG'));

  return (
    <input
      ref={inputRef}
      type="text"
      inputMode="numeric"
      pattern="[0-9]*"
      title={title}
      placeholder={placeholder}
      value={display}
      onFocus={() => {
        setFocused(true);
        setRaw(value === 0 ? '' : String(value));
      }}
      onChange={(e) => {
        const digits = e.target.value.replace(/[^0-9]/g, '');
        setRaw(digits);
        onChange(digits === '' ? 0 : parseInt(digits, 10));
      }}
      onBlur={() => {
        setFocused(false);
        if (raw === '') onChange(0);
      }}
      className={className}
    />
  );
}

export function Tax() {
  const currentYear = new Date().getFullYear();

  const [availableYears, setAvailableYears] = useState<number[]>([]);
  const [selectedYear, setSelectedYear] = useState<number>(currentYear);
  const [activePreset, setActivePreset] = useState<Preset>('full_year');
  const [startDate, setStartDate] = useState(yearStart(currentYear));
  const [endDate, setEndDate]     = useState(yearEnd(currentYear));

  const [summary, setSummary]   = useState<TaxSummary | null>(null);
  const [loading, setLoading]   = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError]       = useState<string | null>(null);

  // Balance sheet inputs for CIT template
  const [shareCapital, setShareCapital]           = useState(100_000);
  const [retainedEarningsBF, setRetainedEarningsBF] = useState(0);
  const [shortTermDebt, setShortTermDebt]         = useState(0);
  const [otherReserves, setOtherReserves]         = useState(0);

  // Load available years from transactions
  useEffect(() => {
    getTaxYears().then((yrs) => {
      setAvailableYears(yrs);
      if (yrs.length > 0) {
        const best = yrs[0]; // already sorted desc
        setSelectedYear(best);
        const p = buildPresets(best);
        setStartDate(p.full_year.start);
        setEndDate(p.full_year.end);
      }
    });
  }, []);

  // When year changes, re-apply the active non-custom preset for the new year
  const handleYearChange = (year: number) => {
    setSelectedYear(year);
    if (activePreset !== 'custom') {
      const p = buildPresets(year);
      setStartDate(p[activePreset].start);
      setEndDate(p[activePreset].end);
    }
  };

  const applyPreset = (p: Exclude<Preset, 'custom'>) => {
    const presets = buildPresets(selectedYear);
    setActivePreset(p);
    setStartDate(presets[p].start);
    setEndDate(presets[p].end);
  };

  const fetchSummary = useCallback(() => {
    if (!startDate || !endDate) return;
    setLoading(true);
    setError(null);
    getTaxSummary({ start_date: startDate, end_date: endDate })
      .then(setSummary)
      .catch(() => setError('Failed to load tax summary'))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);

  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await exportCITExcel({
        start_date: startDate,
        end_date: endDate,
        share_capital: shareCapital,
        retained_earnings_bf: retainedEarningsBF,
        short_term_debt: shortTermDebt,
        other_reserves: otherReserves,
      });
      const presets = buildPresets(selectedYear);
      const label = activePreset === 'custom'
        ? `${startDate}_${endDate}`
        : `${selectedYear}_${presets[activePreset].label.replace(/\s*\(.*\)/, '').trim().replace(/\s/g, '_')}`;
      downloadBlob(blob, `CIT_Return_${label}.xlsx`);
    } catch {
      setError('Export failed — ensure the CIT template is on the server');
    } finally {
      setExporting(false);
    }
  };

  const presets = buildPresets(selectedYear);
  const yearOptions = availableYears.length > 0
    ? availableYears
    : Array.from({ length: 5 }, (_, i) => currentYear - i);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Calculator className="h-6 w-6 text-primary" />
            Nigeria CIT Return
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Company Income Tax (CITA) computation from your transaction data
          </p>
        </div>
        <Button type="button" onClick={handleExport} disabled={exporting || !summary} className="gap-2 shrink-0">
          <FileSpreadsheet className="h-4 w-4" />
          {exporting ? 'Generating…' : 'Download CIT Template'}
        </Button>
      </div>

      {/* Date range controls */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <CalendarRange className="h-4 w-4 text-primary" />
            Assessment Period
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">

          {/* Year selector + preset chips on one row */}
          <div className="flex flex-wrap items-center gap-2">
            <select
              title="Select assessment year"
              value={selectedYear}
              onChange={(e) => handleYearChange(Number(e.target.value))}
              className="rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              {yearOptions.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>

            <div className="h-5 w-px bg-border" />

            {(Object.entries(presets) as [Exclude<Preset,'custom'>, { label: string }][]).map(([key, { label }]) => (
              <button
                type="button"
                key={key}
                onClick={() => applyPreset(key)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ${
                  activePreset === key
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-background border-border text-muted-foreground hover:text-foreground hover:border-foreground/40'
                }`}
              >
                {label}
              </button>
            ))}

            <button
              type="button"
              onClick={() => setActivePreset('custom')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ${
                activePreset === 'custom'
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'bg-background border-border text-muted-foreground hover:text-foreground hover:border-foreground/40'
              }`}
            >
              Custom
            </button>
          </div>

          {/* Date inputs */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <label htmlFor="cit-start" className="text-xs text-muted-foreground whitespace-nowrap">From</label>
              <input
                id="cit-start"
                type="date"
                title="Assessment period start date"
                value={startDate}
                onChange={(e) => { setStartDate(e.target.value); setActivePreset('custom'); }}
                className="rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div className="flex items-center gap-2">
              <label htmlFor="cit-end" className="text-xs text-muted-foreground whitespace-nowrap">To</label>
              <input
                id="cit-end"
                type="date"
                title="Assessment period end date"
                value={endDate}
                onChange={(e) => { setEndDate(e.target.value); setActivePreset('custom'); }}
                className="rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            {activePreset === 'custom' && (
              <Button type="button" size="sm" variant="outline" onClick={fetchSummary}>
                Apply
              </Button>
            )}
          </div>

          {summary && (
            <p className="text-xs text-muted-foreground">
              Showing: <span className="font-medium text-foreground">{summary.period_label}</span>
              {' · '}{summary.transaction_count} transactions
            </p>
          )}
        </CardContent>
      </Card>

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {loading && (
        <div className="text-center py-16 text-muted-foreground">Computing tax figures…</div>
      )}

      {!loading && summary && (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                  Total Revenue
                  <HelpTooltip
                    content={"Total income received in the period: school fees, exam fees, book sales, grants, and other operating income.\n\nUsed to determine your company size tier under CITA:\n· ≤ ₦25M = Small (0% CIT)\n· ₦25M–₦100M = Medium (20%)\n· > ₦100M = Large (30%)"}
                    align="left"
                  />
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-xl font-bold text-income">{formatCurrency(summary.total_revenue)}</p>
                <p className="text-xs text-muted-foreground mt-0.5">{summary.transaction_count} transactions</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                  Total Expenses
                  <HelpTooltip
                    content={"Total allowable expenses deducted from income to arrive at Profit Before Tax.\n\nIncludes salaries, utilities, repairs, stationery, and depreciation from the Asset Register.\n\nNote: Certain expenses (donations, entertainment, fines, depreciation) are non-allowable for CIT and are added back in the computation."}
                    align="left"
                  />
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-xl font-bold text-expense">{formatCurrency(summary.total_admin_expenses)}</p>
                <p className="text-xs text-muted-foreground mt-0.5">Admin & operating costs</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                  Chargeable Income
                  <HelpTooltip
                    content={"Chargeable Income = Profit Before Tax + Non-Allowable Add-Backs\n\nNon-allowable items are added back because FIRS does not permit their deduction:\n· Depreciation (replaced by Capital Allowances)\n· Donations & entertainment above threshold\n· Fines and penalties\n\nThe CIT rate is applied to this adjusted figure."}
                    align="center"
                  />
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className={`text-xl font-bold ${summary.adjusted_profit >= 0 ? 'text-foreground' : 'text-expense'}`}>
                  {formatCurrency(summary.adjusted_profit)}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">After add-backs</p>
              </CardContent>
            </Card>

            {/* Tax Payable — the destination figure of the calculation, visually distinct from its 3 inputs */}
            <Card className={summary.effective_tax_payable > 0 ? 'bg-primary text-primary-foreground border-0' : ''}>
              <CardHeader className="pb-1 pt-4 px-4">
                <CardTitle className={`text-xs font-medium uppercase tracking-wide flex items-center gap-1.5 ${summary.effective_tax_payable > 0 ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
                  Tax Payable
                  <HelpTooltip
                    className={summary.effective_tax_payable > 0 ? 'text-primary-foreground/70 [&_button:hover]:text-primary-foreground [&_button:hover]:bg-white/10' : ''}
                    content={"Effective Tax = higher of:\n(a) CIT on Chargeable Income at 0% / 20% / 30%\n(b) Minimum Tax: 0.5% × Total Turnover\n\nThe minimum tax ensures companies with low or nil profits still pay a floor amount.\n\nExample (Medium company):\n· Chargeable income: ₦600,000 × 20% = ₦120,000\n· Minimum tax: ₦8,000,000 × 0.5% = ₦40,000\n· Tax payable = ₦120,000 (higher)"}
                    align="right"
                  />
                </CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <p className="text-xl font-bold font-display">{formatCurrency(summary.effective_tax_payable)}</p>
                <p className={`text-xs mt-0.5 ${summary.effective_tax_payable > 0 ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
                  {summary.company_size} · {(summary.tax_rate * 100).toFixed(0)}%
                  {summary.minimum_tax_applies && ' (min. tax)'}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Flagged category warnings */}
          {summary.flagged_categories && summary.flagged_categories.length > 0 && (
            <div className="space-y-2">
              {summary.flagged_categories.map((flag) => (
                <div
                  key={flag.category}
                  className="flex items-start gap-3 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm"
                >
                  <AlertCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <span className="font-semibold text-destructive">{flag.category}</span>
                    <span className="text-destructive/90"> — {formatCurrency(flag.amount)} excluded from CIT.</span>
                    <p className="text-destructive/80 mt-0.5">{flag.reason}</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* CIT Computation */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-primary" />
                  CIT Computation
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                <SectionRow label="Total Revenue" amount={summary.total_revenue} bold positive={summary.total_revenue > 0} />
                <SectionRow label="Total Other Income" amount={summary.total_other_income} indent positive={summary.total_other_income > 0} />
                <SectionRow label="Total Admin Expenses" amount={-summary.total_admin_expenses} indent positive={false} />
                <SectionRow label="Profit Before Tax" amount={summary.profit_before_tax} bold positive={summary.profit_before_tax >= 0} />
                <SectionRow
                  label="Add Backs (Non-Allowable)"
                  amount={summary.total_add_backs}
                  indent
                  positive={false}
                  muted
                  help={"Non-allowable expenses are added back to profit because FIRS does not permit their deduction:\n\n· Depreciation — FIRS uses Capital Allowances instead\n· Donations & charity above statutory threshold\n· Entertainment above ₦2,000 per person\n· Fines, penalties, and legal settlements\n\nAdding them back increases chargeable income, resulting in a higher (more accurate) tax base."}
                />
                <SectionRow label="Chargeable / Adjusted Profit" amount={summary.adjusted_profit} bold positive={summary.adjusted_profit >= 0} />

                <div className="pt-3 border-t border-border mt-2 space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground flex items-center gap-1.5">
                      Company Size
                      <HelpTooltip
                        content={"Company size is determined by Total Revenue (Turnover):\n\n· Small: ≤ ₦25,000,000 → 0% CIT (full exemption)\n· Medium: ₦25M – ₦100M → 20% CIT\n· Large: > ₦100,000,000 → 30% CIT\n\nSize classification uses your gross revenue before any deductions."}
                        align="left"
                      />
                    </span>
                    <span className="font-medium">{summary.company_size}</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">CIT Rate</span>
                    <span className="font-medium">{(summary.tax_rate * 100).toFixed(0)}%</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Computed Tax</span>
                    <span className="font-medium tabular-nums">{formatCurrency(summary.tax_payable)}</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground flex items-center gap-1.5">
                      Minimum Tax (0.5% of turnover)
                      <HelpTooltip
                        content={"Minimum Tax = 0.5% × Total Gross Revenue\n\nApplies to all companies except:\n· Companies in their first 4 years of business\n· Companies with ≥ 25% imported equity\n· Agricultural companies\n\nPurpose: FIRS wants a floor payment even from loss-making companies.\n\nExample: ₦10,000,000 revenue × 0.5% = ₦50,000 minimum tax"}
                        align="left"
                      />
                    </span>
                    <span className="font-medium tabular-nums">{formatCurrency(summary.minimum_tax)}</span>
                  </div>
                  <div className="flex items-center justify-between text-base font-bold pt-1 border-t border-border">
                    <span className="flex items-center gap-1.5">
                      Effective Tax Payable
                      <HelpTooltip
                        content={"Effective Tax = max(Computed CIT, Minimum Tax)\n\nThe law requires you to pay whichever is higher:\n· Computed CIT: Chargeable Income × CIT Rate\n· Minimum Tax: 0.5% × Gross Revenue\n\nThis is your total CIT liability. File this amount with FIRS on your annual CIT return (due 6 months after year-end)."}
                        align="right"
                      />
                    </span>
                    <span className="text-primary tabular-nums">{formatCurrency(summary.effective_tax_payable)}</span>
                  </div>

                  {summary.minimum_tax_applies && (
                    <div className="flex items-start gap-2 rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700 mt-1">
                      <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                      Minimum tax applies — turnover-based (0.5%) exceeds profit-based tax.
                    </div>
                  )}
                  {summary.tax_rate === 0 && (
                    <div className="flex items-start gap-2 rounded-md bg-green-50 border border-green-200 px-3 py-2 text-xs text-green-700 mt-1">
                      <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                      Small company exemption applies — CIT rate is 0%.
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Breakdowns */}
            <div className="space-y-4">
              <CollapsibleSection title="Revenue by Sector" total={summary.total_revenue} items={summary.revenue_by_sector} colorClass="text-income" defaultOpen />
              <CollapsibleSection title="Other Income" total={summary.total_other_income} items={summary.other_income} colorClass="text-income" />
              <CollapsibleSection title="Administrative Expenses" total={summary.total_admin_expenses} items={summary.admin_expenses} colorClass="text-expense" />
              <CollapsibleSection title="Non-Allowable Add-Backs" total={summary.total_add_backs} items={summary.add_backs} colorClass="text-brand-accent" />
            </div>
          </div>

          {/* Balance sheet inputs */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <FileSpreadsheet className="h-4 w-4 text-primary" />
                Statement of Financial Position Inputs
                <span className="text-xs font-normal text-muted-foreground">(written into CIT template export)</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {([
                  { label: 'Share Capital (₦)', value: shareCapital, setter: setShareCapital,
                    help: 'Issued share capital of the company. Default ₦100,000 (Nigerian minimum).' },
                  { label: 'Retained Earnings B/F (₦)', value: retainedEarningsBF, setter: setRetainedEarningsBF,
                    help: 'Retained earnings carried forward from the prior year. Enter 0 for first-year filings.' },
                  { label: 'Outstanding Loans (₦)', value: shortTermDebt, setter: setShortTermDebt,
                    help: 'Short-term loan balances not tracked as transactions (e.g. cooperative society outstanding principal).' },
                  { label: 'Other Reserves (₦)', value: otherReserves, setter: setOtherReserves,
                    help: 'Other equity reserves such as capital contribution above share capital or revaluation surplus.' },
                ] as const).map(({ label, value, setter, help }) => (
                  <div key={label} className="space-y-1">
                    <label className="text-xs font-medium text-muted-foreground flex items-center gap-1">
                      {label}
                      <HelpTooltip content={help} align="left" />
                    </label>
                    <NumericInput
                      value={value}
                      onChange={setter}
                      title={label}
                      className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Filing instructions */}
          <Card className="bg-secondary/50 border-secondary">
            <CardContent className="pt-4 pb-4">
              <div className="flex items-start gap-3">
                <Download className="h-5 w-5 text-primary mt-0.5 shrink-0" />
                <div className="space-y-1">
                  <p className="text-sm font-medium text-secondary-foreground">How to file with FIRS</p>
                  <ol className="text-xs text-secondary-foreground/80 space-y-0.5 list-decimal list-inside">
                    <li>Click <strong>Download CIT Template</strong> above to get your pre-filled Excel file.</li>
                    <li>Log in to the NRS Self-Service Portal and click <strong>File Now</strong>.</li>
                    <li>Upload the filled Excel template — the portal will compute your tax liability.</li>
                    <li>Review the generated figures, complete any remaining sections, and submit.</li>
                  </ol>
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {!loading && !summary && !error && (
        <div className="text-center py-16 text-muted-foreground">
          <TrendingDown className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>No transaction data for the selected period.</p>
          <p className="text-sm mt-1">Import transactions or choose a different date range.</p>
        </div>
      )}
    </div>
  );
}
