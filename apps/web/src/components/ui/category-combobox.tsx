import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Search } from 'lucide-react';
import { cn } from '../../lib/utils';

interface CategoryComboboxProps {
  value?: string;
  categories: string[];
  placeholder?: string;
  onChange: (value: string) => void;
}

export function CategoryCombobox({
  value,
  categories,
  placeholder = 'Select category',
  onChange,
}: CategoryComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = query.trim()
    ? categories.filter((c) => c.toLowerCase().includes(query.toLowerCase()))
    : categories;

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery('');
      }
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Focus search input when dropdown opens
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 0);
    } else {
      setQuery('');
    }
  }, [open]);

  function select(cat: string) {
    onChange(cat);
    setOpen(false);
    setQuery('');
  }

  return (
    <div ref={containerRef} className="relative">
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm ring-offset-background transition-colors',
          'hover:bg-accent/30 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
          open && 'ring-2 ring-ring ring-offset-2',
          !value && 'text-muted-foreground'
        )}
      >
        <span className="truncate">{value || placeholder}</span>
        <ChevronDown className={cn('h-4 w-4 text-muted-foreground shrink-0 transition-transform', open && 'rotate-180')} />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute z-50 mt-1 w-full rounded-md border border-border bg-popover shadow-md">
          {/* Search input */}
          <div className="flex items-center border-b border-border px-3 py-2 gap-2">
            <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search categories…"
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>

          {/* List */}
          <div className="max-h-56 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-muted-foreground">No categories match</p>
            ) : (
              filtered.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => select(cat)}
                  className={cn(
                    'flex w-full items-center gap-2 px-3 py-1.5 text-sm text-left hover:bg-accent hover:text-accent-foreground transition-colors',
                    cat === value && 'bg-accent/60 font-medium'
                  )}
                >
                  <Check className={cn('h-3.5 w-3.5 shrink-0', cat === value ? 'opacity-100 text-primary' : 'opacity-0')} />
                  {cat}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
