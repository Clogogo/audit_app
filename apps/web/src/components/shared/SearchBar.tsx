import { Search } from 'lucide-react';
import { Input } from '../ui/input';
import { Badge } from '../ui/badge';

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  resultCount?: number;
}

export function SearchBar({ value, onChange, placeholder = 'Search...', resultCount }: SearchBarProps) {
  return (
    <div className="flex items-center gap-2">
      <div className="relative flex-1 max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="pl-9"
        />
      </div>
      {resultCount !== undefined && (
        <Badge variant="outline" className="text-sm">
          {resultCount} result{resultCount !== 1 ? 's' : ''}
        </Badge>
      )}
    </div>
  );
}
