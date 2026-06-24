import { useState, useMemo } from 'react';
import { CalendarClock, ChevronLeft, ChevronRight, AlertCircle, Clock, CheckCircle2, Info, X } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';

// ── Types ─────────────────────────────────────────────────────────────────────

type TaxType = 'CIT' | 'PAYE' | 'VAT' | 'WHT' | 'Pension' | 'NSITF' | 'ITF' | 'CAC' | 'EDT';

interface TaxEvent {
  id: string;
  taxType: TaxType;
  label: string;
  day: number;
  month: number;
  frequency: 'monthly' | 'annual';
  description: string;
  authority: string;
  rate: string;
  penaltyNote: string;
}

// ── Colours ───────────────────────────────────────────────────────────────────

const TYPE_PILL: Record<TaxType, string> = {
  CIT:     'bg-purple-500 text-white',
  PAYE:    'bg-blue-500 text-white',
  VAT:     'bg-indigo-500 text-white',
  WHT:     'bg-cyan-600 text-white',
  Pension: 'bg-green-500 text-white',
  NSITF:   'bg-teal-500 text-white',
  ITF:     'bg-orange-500 text-white',
  CAC:     'bg-amber-500 text-white',
  EDT:     'bg-pink-500 text-white',
};

const TYPE_BADGE: Record<TaxType, string> = {
  CIT:     'bg-purple-100 text-purple-800 border-purple-300',
  PAYE:    'bg-blue-100 text-blue-800 border-blue-300',
  VAT:     'bg-indigo-100 text-indigo-800 border-indigo-300',
  WHT:     'bg-cyan-100 text-cyan-700 border-cyan-300',
  Pension: 'bg-green-100 text-green-800 border-green-300',
  NSITF:   'bg-teal-100 text-teal-800 border-teal-300',
  ITF:     'bg-orange-100 text-orange-800 border-orange-300',
  CAC:     'bg-amber-100 text-amber-800 border-amber-300',
  EDT:     'bg-pink-100 text-pink-800 border-pink-300',
};

// ── Event definitions (Dec 31 year-end) ───────────────────────────────────────

function monthlyEvent(
  taxType: TaxType, day: number, month: number,
  label: string, description: string,
  authority: string, rate: string, penaltyNote: string,
): TaxEvent {
  return {
    id: `${taxType}-m${month}`,
    taxType, label, day, month,
    frequency: 'monthly',
    description, authority, rate, penaltyNote,
  };
}

function annualEvent(
  taxType: TaxType, day: number, month: number,
  label: string, description: string,
  authority: string, rate: string, penaltyNote: string,
): TaxEvent {
  return {
    id: `${taxType}-annual`,
    taxType, label, day, month,
    frequency: 'annual',
    description, authority, rate, penaltyNote,
  };
}

// Build all 12 months × recurring events + annual events
function buildAllEvents(): TaxEvent[] {
  const events: TaxEvent[] = [];

  for (let m = 1; m <= 12; m++) {
    // For monthly taxes the "for month X" text means they cover the PRIOR month's activity
    events.push(monthlyEvent('PAYE',    10, m, `PAYE — Remittance`,
      `Remit PAYE deductions from employee salaries for the prior month to FIRS by the 10th.`,
      'FIRS', 'Progressive 7%–24% of taxable income',
      '10% penalty on unpaid amount + 5% monthly interest.'));

    events.push(monthlyEvent('VAT',     21, m, `VAT — Filing & Remittance`,
      `File VAT returns and remit 7.5% VAT collected in the prior month to FIRS via e-platform.`,
      'FIRS', '7.5% of taxable supplies',
      '5% penalty on unpaid VAT + 2% monthly interest.'));

    events.push(monthlyEvent('WHT',     21, m, `WHT — Remittance`,
      `Remit Withholding Tax deducted from vendors, contractors, and service providers.`,
      'FIRS', '5%–10% depending on payment type',
      '10% penalty on outstanding WHT + 5% monthly interest.'));

    events.push(monthlyEvent('Pension', 28, m, `Pension — PENCOM Contribution`,
      `Remit employer (10%) + employee (8%) pension contributions to your Pension Fund Administrator.`,
      'PENCOM / PFA', '18% of monthly emoluments',
      '2% monthly penalty on outstanding contributions.'));

    events.push(monthlyEvent('NSITF',   28, m, `NSITF — Monthly Levy`,
      `Remit 1% of total monthly payroll as Nigeria Social Insurance Trust Fund levy.`,
      'NSITF', '1% of monthly payroll',
      '2% per month on outstanding levy.'));
  }

  // Annual deadlines (Dec 31 year-end)
  events.push(annualEvent('ITF', 28, 2, 'ITF — Annual Levy',
    'Pay 1% of annual gross payroll as Industrial Training Fund levy. Due within 60 days of year-end.',
    'ITFC', '1% of annual payroll',
    '5% penalty per annum + potential prosecution.'));

  events.push(annualEvent('CAC', 31, 3, 'CAC — Annual Return',
    'File Annual Return with the Corporate Affairs Commission within 42 days of your AGM.',
    'CAC', 'Filing fee ₦3,000+',
    '₦10,000 fine per year of default. Directors may be personally liable.'));

  events.push(annualEvent('CIT', 30, 6, 'CIT — Self-Assessment Return',
    'File Company Income Tax self-assessment return and pay CIT liability. Due 6 months after year-end.',
    'FIRS', '0% / 20% / 30% of chargeable profit',
    '10% penalty + 5% per annum interest. Late filing: ₦25,000 (1st month) + ₦5,000/month thereafter.'));

  events.push(annualEvent('EDT', 30, 6, 'EDT — Education Development Tax',
    'Pay Education Development Tax at 0.5% of assessable profits. Filed alongside CIT return.',
    'FIRS', '0.5% of assessable profit',
    'Same penalties as CIT — 10% + interest.'));

  return events;
}

const ALL_EVENTS = buildAllEvents();

// ── Helpers ───────────────────────────────────────────────────────────────────

type Status = 'today' | 'overdue' | 'due-soon' | 'upcoming' | 'past';

function eventStatus(year: number, month: number, day: number, today: Date): Status {
  const dl = new Date(year, month - 1, day);
  const todayMid = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const diff = Math.ceil((dl.getTime() - todayMid.getTime()) / 86_400_000);
  if (diff === 0) return 'today';
  if (diff < 0)  return 'past';
  if (diff <= 7) return 'due-soon';
  if (diff <= 30) return 'upcoming';
  return 'upcoming';
}

const DAYS_OF_WEEK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH_NAMES  = ['January','February','March','April','May','June',
                      'July','August','September','October','November','December'];

// ── Component ─────────────────────────────────────────────────────────────────

export function TaxCalendar() {
  const today = useMemo(() => new Date(), []);

  const [viewYear,  setViewYear]  = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth() + 1); // 1-12
  const [selected,  setSelected]  = useState<{ day: number; events: TaxEvent[] } | null>(null);
  const [filterType, setFilterType] = useState<TaxType | 'ALL'>('ALL');

  // Navigation
  const prevMonth = () => {
    if (viewMonth === 1) { setViewMonth(12); setViewYear(y => y - 1); }
    else setViewMonth(m => m - 1);
    setSelected(null);
  };
  const nextMonth = () => {
    if (viewMonth === 12) { setViewMonth(1); setViewYear(y => y + 1); }
    else setViewMonth(m => m + 1);
    setSelected(null);
  };
  const goToday = () => {
    setViewYear(today.getFullYear());
    setViewMonth(today.getMonth() + 1);
    setSelected(null);
  };

  // Calendar grid
  const daysInMonth  = new Date(viewYear, viewMonth, 0).getDate();
  const firstWeekDay = new Date(viewYear, viewMonth - 1, 1).getDay(); // 0=Sun

  // Events for this month filtered
  const monthEvents = useMemo(() => {
    return ALL_EVENTS.filter(e =>
      e.month === viewMonth &&
      (filterType === 'ALL' || e.taxType === filterType)
    );
  }, [viewMonth, filterType]);

  // Group events by day for quick lookup
  const eventsByDay = useMemo(() => {
    const map = new Map<number, TaxEvent[]>();
    for (const ev of monthEvents) {
      const arr = map.get(ev.day) ?? [];
      arr.push(ev);
      map.set(ev.day, arr);
    }
    return map;
  }, [monthEvents]);

  // Upcoming (next 30 days)
  const upcoming = useMemo(() => {
    const end = new Date(today); end.setDate(end.getDate() + 30);
    return ALL_EVENTS
      .map(e => {
        const dl = new Date(viewYear, e.month - 1, e.day);
        const status = eventStatus(viewYear, e.month, e.day, today);
        return { ...e, deadline: dl, status };
      })
      .filter(e => e.deadline >= today && e.deadline <= end)
      .sort((a, b) => a.deadline.getTime() - b.deadline.getTime())
      .slice(0, 6);
  }, [viewYear, today]);

  const TAX_TYPES: TaxType[] = ['CIT','PAYE','VAT','WHT','Pension','NSITF','ITF','CAC','EDT'];

  // Build grid cells: leading blanks + days + trailing blanks
  const totalCells = Math.ceil((firstWeekDay + daysInMonth) / 7) * 7;
  const cells: Array<number | null> = [
    ...Array(firstWeekDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
    ...Array(totalCells - firstWeekDay - daysInMonth).fill(null),
  ];

  const isToday = (day: number) =>
    day === today.getDate() &&
    viewMonth === today.getMonth() + 1 &&
    viewYear  === today.getFullYear();

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <CalendarClock className="h-6 w-6 text-primary" />
          Tax Calendar
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Nigerian tax filing deadlines — Dec 31 financial year-end
        </p>
      </div>

      {/* Upcoming strip */}
      {upcoming.length > 0 && (
        <Card className="border-amber-200 bg-amber-50/40">
          <CardContent className="pt-3 pb-3">
            <p className="text-xs font-semibold text-amber-800 mb-2 flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5" /> Next 30 days
            </p>
            <div className="flex flex-wrap gap-2">
              {upcoming.map(e => (
                <button
                  key={e.id}
                  type="button"
                  onClick={() => {
                    setViewMonth(e.month);
                    setSelected({ day: e.day, events: eventsByDay.get(e.day) ?? [e] });
                  }}
                  className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-opacity hover:opacity-80 ${TYPE_BADGE[e.taxType]}`}
                >
                  <span>{e.taxType}</span>
                  <span className="opacity-60">·</span>
                  <span>{e.deadline.toLocaleDateString('en-NG',{day:'numeric',month:'short'})}</span>
                  {e.status === 'due-soon' && <span className="ml-0.5 text-amber-600 font-bold">!</span>}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Filter chips */}
      <div className="flex flex-wrap gap-1.5 items-center">
        <button
          type="button"
          onClick={() => setFilterType('ALL')}
          className={`rounded-full px-3 py-0.5 text-xs font-medium border transition-colors ${filterType === 'ALL' ? 'bg-foreground text-background border-foreground' : 'border-border text-muted-foreground hover:bg-accent'}`}
        >
          All
        </button>
        {TAX_TYPES.map(t => (
          <button
            key={t}
            type="button"
            onClick={() => setFilterType(filterType === t ? 'ALL' : t)}
            className={`rounded-full px-2.5 py-0.5 text-xs font-semibold border transition-all ${filterType === t ? TYPE_PILL[t] + ' border-transparent scale-105 shadow' : TYPE_BADGE[t] + ' opacity-70 hover:opacity-100'}`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Calendar card */}
      <Card className="overflow-hidden">
        {/* Month navigator */}
        <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/20">
          <button type="button" aria-label="Previous month" onClick={prevMonth} className="rounded p-1.5 hover:bg-accent transition-colors">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <div className="flex items-center gap-3">
            <h2 className="text-base font-bold tracking-tight">
              {MONTH_NAMES[viewMonth - 1]} {viewYear}
            </h2>
            <button
              type="button"
              onClick={goToday}
              className="text-xs text-primary font-medium underline-offset-2 hover:underline"
            >
              Today
            </button>
          </div>
          <button type="button" aria-label="Next month" onClick={nextMonth} className="rounded p-1.5 hover:bg-accent transition-colors">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        {/* Day-of-week headers */}
        <div className="grid grid-cols-7 border-b">
          {DAYS_OF_WEEK.map(d => (
            <div key={d} className="py-2 text-center text-xs font-semibold text-muted-foreground tracking-wide">
              {d}
            </div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="grid grid-cols-7">
          {cells.map((day, idx) => {
            const dayEvents = day ? (eventsByDay.get(day) ?? []) : [];
            const isCurrentDay = day ? isToday(day) : false;
            const isSelected   = day !== null && selected?.day === day;
            const isBlank      = day === null;

            return (
              <div
                key={idx}
                onClick={() => {
                  if (!day) return;
                  setSelected(isSelected ? null : { day, events: dayEvents });
                }}
                className={[
                  'min-h-[80px] border-r border-b p-1.5 transition-colors relative',
                  isBlank   ? 'bg-muted/20 cursor-default' : 'cursor-pointer hover:bg-accent/40',
                  isSelected && !isBlank ? 'bg-primary/8 ring-2 ring-inset ring-primary' : '',
                  // last column — no right border
                  (idx + 1) % 7 === 0 ? 'border-r-0' : '',
                ].join(' ')}
              >
                {/* Day number */}
                {day && (
                  <div className={[
                    'h-6 w-6 flex items-center justify-center rounded-full text-xs font-semibold mb-1',
                    isCurrentDay
                      ? 'bg-primary text-primary-foreground'
                      : 'text-foreground',
                  ].join(' ')}>
                    {day}
                  </div>
                )}

                {/* Event pills */}
                <div className="space-y-0.5">
                  {dayEvents.slice(0, 3).map(ev => (
                    <div
                      key={ev.id}
                      className={`rounded px-1 py-0.5 text-[10px] font-semibold truncate leading-tight ${TYPE_PILL[ev.taxType]}`}
                    >
                      {ev.taxType}
                    </div>
                  ))}
                  {dayEvents.length > 3 && (
                    <div className="text-[10px] text-muted-foreground font-medium pl-1">
                      +{dayEvents.length - 3} more
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* Selected day detail panel */}
      {selected && selected.events.length > 0 && (
        <Card className="border-primary/30">
          <CardHeader className="pb-2 pt-4 flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-semibold">
              {MONTH_NAMES[viewMonth - 1]} {selected.day}, {viewYear}
              <span className="ml-2 text-xs text-muted-foreground font-normal">
                — {selected.events.length} deadline{selected.events.length > 1 ? 's' : ''}
              </span>
            </CardTitle>
            <button type="button" aria-label="Close detail panel" onClick={() => setSelected(null)} className="rounded p-1 hover:bg-accent">
              <X className="h-4 w-4 text-muted-foreground" />
            </button>
          </CardHeader>
          <CardContent className="space-y-3 pb-4">
            {selected.events.map(ev => {
              const status = eventStatus(viewYear, ev.month, ev.day, today);
              const dl = new Date(viewYear, ev.month - 1, ev.day);
              const diffDays = Math.ceil((dl.getTime() - new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()) / 86_400_000);

              const statusBadge =
                status === 'today'    ? <span className="flex items-center gap-1 text-xs font-bold text-red-600"><AlertCircle className="h-3 w-3"/>Due Today</span>  :
                status === 'due-soon' ? <span className="flex items-center gap-1 text-xs font-bold text-amber-600"><Clock className="h-3 w-3"/>Due in {diffDays}d</span> :
                status === 'past'     ? <span className="flex items-center gap-1 text-xs text-muted-foreground"><CheckCircle2 className="h-3 w-3"/>{Math.abs(diffDays)}d ago</span> :
                                        <span className="flex items-center gap-1 text-xs text-blue-600"><Info className="h-3 w-3"/>In {diffDays} days</span>;

              return (
                <div key={ev.id} className={`rounded-lg border p-3 ${status === 'past' ? 'opacity-60' : ''}`}>
                  <div className="flex items-start gap-2.5">
                    <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-bold border ${TYPE_BADGE[ev.taxType]}`}>
                      {ev.taxType}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <span className="font-semibold text-sm">{ev.label}</span>
                        {statusBadge}
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">{ev.description}</p>
                      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                        <span className="text-muted-foreground">🏛 <strong>Authority:</strong> {ev.authority}</span>
                        <span className="text-muted-foreground">📊 <strong>Rate:</strong> {ev.rate}</span>
                        <span className={`${ev.frequency === 'monthly' ? 'text-blue-600' : 'text-purple-600'}`}>
                          {ev.frequency === 'monthly' ? '↻ Monthly' : '📆 Annual'}
                        </span>
                      </div>
                      <details className="mt-2">
                        <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground select-none">
                          ⚠ Penalty for late filing
                        </summary>
                        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1 mt-1">
                          {ev.penaltyNote}
                        </p>
                      </details>
                    </div>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* Quick reference table */}
      <Card>
        <CardHeader className="pb-2 pt-4">
          <CardTitle className="text-sm flex items-center gap-2">
            <Info className="h-4 w-4 text-muted-foreground" />
            Quick Reference — Annual Tax Obligations (Dec 31 Year-End)
          </CardTitle>
        </CardHeader>
        <CardContent className="pb-4">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="py-2 pr-4 text-left font-semibold">Tax</th>
                  <th className="py-2 pr-4 text-left font-semibold">Frequency</th>
                  <th className="py-2 pr-4 text-left font-semibold">Deadline</th>
                  <th className="py-2 pr-4 text-left font-semibold">Authority</th>
                  <th className="py-2 text-left font-semibold">Rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {[
                  { t:'CIT',     freq:'Annual',  due:'June 30',               auth:'FIRS',   rate:'0% / 20% / 30% of profit' },
                  { t:'EDT',     freq:'Annual',  due:'June 30',               auth:'FIRS',   rate:'0.5% of assessable profit' },
                  { t:'PAYE',    freq:'Monthly', due:'10th of following month',auth:'FIRS',  rate:'Progressive 7%–24%' },
                  { t:'VAT',     freq:'Monthly', due:'21st of following month',auth:'FIRS',  rate:'7.5% of taxable supplies' },
                  { t:'WHT',     freq:'Monthly', due:'21st of following month',auth:'FIRS',  rate:'5%–10% on payments' },
                  { t:'Pension', freq:'Monthly', due:'28th of month',          auth:'PENCOM', rate:'18% of emoluments' },
                  { t:'NSITF',   freq:'Monthly', due:'28th of month',          auth:'NSITF',  rate:'1% of monthly payroll' },
                  { t:'ITF',     freq:'Annual',  due:'Feb 28',                 auth:'ITFC',   rate:'1% of annual payroll' },
                  { t:'CAC',     freq:'Annual',  due:'Within 42 days of AGM',  auth:'CAC',    rate:'Filing fee ₦3,000+' },
                ].map(row => (
                  <tr key={row.t} className="hover:bg-muted/30">
                    <td className="py-2 pr-4">
                      <span className={`rounded-full px-2 py-0.5 border text-xs font-bold ${TYPE_BADGE[row.t as TaxType]}`}>
                        {row.t}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-muted-foreground">{row.freq}</td>
                    <td className="py-2 pr-4 font-medium">{row.due}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{row.auth}</td>
                    <td className="py-2">{row.rate}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
