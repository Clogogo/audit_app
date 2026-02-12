import { Badge } from './ui/badge';
import type { TransactionType } from '../api/types';

interface CategoryBadgeProps {
  category: string;
  type?: TransactionType;
}

export function CategoryBadge({ category, type }: CategoryBadgeProps) {
  return (
    <Badge variant={type === 'income' ? 'income' : 'expense'}>
      {category}
    </Badge>
  );
}

export function TypeBadge({ type }: { type: TransactionType }) {
  return (
    <Badge variant={type === 'income' ? 'income' : 'expense'}>
      {type === 'income' ? 'Income' : 'Expense'}
    </Badge>
  );
}
