import { useEffect, useRef, useState } from 'react';
import { AlertCircle, FileSpreadsheet, Loader2, Upload } from 'lucide-react';
import { reconcilePayroll } from '../../api/client';
import type { PayrollReconcileResult } from '../../api/types';
import { Button } from '../ui/button';
import { Card, CardContent } from '../ui/card';

type InputMode = 'file' | 'paste';

// Rows copied from Excel/Sheets arrive tab-separated; the API reads them like an uploaded file.
const pastedToFile = (text: string) => new File([text], 'pasted.tsv', { type: 'text/tab-separated-values' });

export function extractErrorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) return 'Please check the month and file, then try again.';
  return 'Reconciliation failed. Please try again.';
}

interface SchedulePanelProps {
  year: number;
  month: number;
  monthLabel: string;
  onResult: (result: PayrollReconcileResult | null) => void;
  /** bump to re-run the reconciliation with the same file/paste (e.g. after the directory was updated) */
  rerunToken?: number;
}

/** Upload or paste the month's payroll schedule and reconcile it with the bank payments. */
export function SchedulePanel({ year, month, monthLabel, onResult, rerunToken = 0 }: SchedulePanelProps) {
  const [mode, setMode] = useState<InputMode>('file');
  const [file, setFile] = useState<File | null>(null);
  const [pasted, setPasted] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestId = useRef(0);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;

  // A schedule belongs to one month: switching month discards the file, the
  // result and any request still in flight.
  useEffect(() => {
    requestId.current += 1;
    setLoading(false);
    setError(null);
    setFile(null);
    setPasted('');
    onResultRef.current(null);
  }, [year, month]);

  const changed = () => { setError(null); onResultRef.current(null); };
  const canRun = mode === 'file' ? file !== null : pasted.trim().length > 0;

  const run = async () => {
    const upload = mode === 'file' ? file : pastedToFile(pasted);
    if (!upload || !canRun) return;
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const res = await reconcilePayroll(upload, year, month);
      if (id === requestId.current) onResultRef.current(res);
    } catch (err) {
      if (id !== requestId.current) return;
      onResultRef.current(null);
      setError(extractErrorMessage(err));
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (rerunToken > 0) void run();
  }, [rerunToken]);

  return (
    <Card>
      <CardContent className="pt-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Payroll schedule — {monthLabel}</h2>
          <div className="flex gap-2" role="group" aria-label="Schedule input">
            <Button type="button" size="sm" variant={mode === 'file' ? 'default' : 'outline'} aria-pressed={mode === 'file'}
              disabled={loading} onClick={() => { setMode('file'); changed(); }}>Upload file</Button>
            <Button type="button" size="sm" variant={mode === 'paste' ? 'default' : 'outline'} aria-pressed={mode === 'paste'}
              disabled={loading} onClick={() => { setMode('paste'); changed(); }}>Paste from Excel</Button>
          </div>
        </div>

        {mode === 'paste' ? (
          <div className="space-y-1">
            <label htmlFor="schedule-paste" className="text-sm font-medium">Paste rows from Excel</label>
            <textarea
              id="schedule-paste"
              rows={6}
              value={pasted}
              disabled={loading}
              onChange={(e) => { setPasted(e.target.value); changed(); }}
              placeholder="Copy the rows in Excel or Google Sheets and paste them here…"
              className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
            />
          </div>
        ) : (
          <div className="space-y-1">
            <label htmlFor="schedule-file" className="text-sm font-medium">Payroll schedule</label>
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                id="schedule-file"
                type="file"
                accept=".xlsx,.xlsm,.csv"
                className="sr-only peer"
                onChange={(e) => { setFile(e.target.files?.[0] ?? null); changed(); }}
              />
              <Button type="button" variant="outline" disabled={loading} onClick={() => inputRef.current?.click()}>
                <FileSpreadsheet className="h-4 w-4 mr-2" />
                {file ? 'Change file' : 'Choose file'}
              </Button>
              <span className="text-sm text-muted-foreground">{file?.name ?? 'No file chosen'}</span>
            </div>
          </div>
        )}

        <div className="flex items-center gap-3">
          <Button type="button" onClick={run} disabled={!canRun || loading}>
            {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Upload className="h-4 w-4 mr-2" />}
            Reconcile
          </Button>
          <p className="text-xs text-muted-foreground">
            A header row is optional. Without one, the leftmost text column is the name, the last money column is the
            net pay, and a long digit column is the account number. Pasted data must be tab-separated, as copied
            straight from Excel or Sheets. Only Salary and Wages bank payments for {monthLabel} are compared.
            A payment within ₦100 of the schedule counts as paid. Nothing is saved.
          </p>
        </div>

        {error && (
          <div role="alert" className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
