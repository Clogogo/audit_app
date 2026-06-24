import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import type { Term } from '../api/types';

const NONE = '__none__';

interface TermSelectProps {
  terms: Term[];
  selectedTermId: number | null;
  onSelectTerm: (term: Term | null) => void;
}

/** Dropdown to pick a saved custom date-range "term" (e.g. a school term). Terms are created on the Staff → Terms page. */
export function TermSelect({ terms, selectedTermId, onSelectTerm }: TermSelectProps) {
  const handleSelect = (value: string) => {
    if (value === NONE) {
      onSelectTerm(null);
      return;
    }
    const term = terms.find((t) => String(t.id) === value);
    if (term) onSelectTerm(term);
  };

  return (
    <Select value={selectedTermId != null ? String(selectedTermId) : NONE} onValueChange={handleSelect}>
      <SelectTrigger className="w-44">
        <SelectValue placeholder="Term" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>No term</SelectItem>
        {(Array.isArray(terms) ? terms : []).map((t) => (
          <SelectItem key={t.id} value={String(t.id)}>{t.name}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
