import { useMemo } from 'react';
import type { ChartAccount } from '../../api/types';

interface AccountSelectProps {
  accounts: ChartAccount[];          // only accounts that can receive postings
  value: string | null;
  onChange: (code: string | null) => void;
  disabled?: boolean;
  label: string;
}

/** Native select (searchable by typing the code), grouped by category and statement section. */
export function AccountSelect({ accounts, value, onChange, disabled, label }: AccountSelectProps) {
  const groups = useMemo(() => {
    const byGroup = new Map<string, ChartAccount[]>();
    for (const a of accounts) {
      const key = `${a.category} › ${a.statement_section}`;
      byGroup.set(key, [...(byGroup.get(key) ?? []), a]);
    }
    return [...byGroup.entries()];
  }, [accounts]);

  return (
    <select
      aria-label={label}
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value || null)}
      className="w-full max-w-xs rounded-md border border-input bg-background px-2 py-1.5 text-xs"
    >
      <option value="">— Not mapped —</option>
      {groups.map(([group, list]) => (
        <optgroup key={group} label={group}>
          {list.map((a) => <option key={a.code} value={a.code}>{a.code} {a.name}</option>)}
        </optgroup>
      ))}
    </select>
  );
}
