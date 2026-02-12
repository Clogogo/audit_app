import { Badge } from './ui/badge';
import type { TransactionType } from '../api/types';

interface CategoryBadgeProps {
  category: string;
  type?: TransactionType;
}

export function CategoryBadge({ category, type }: CategoryBadgeProps) {
  const variant = type === 'income' ? 'income' : type === 'transfer' ? 'secondary' : 'expense';
  return (
    <Badge variant={variant}>
      {category}
    </Badge>
  );
}

export function TypeBadge({ type }: { type: TransactionType }) {
  const variant = type === 'income' ? 'income' : type === 'transfer' ? 'secondary' : 'expense';
  const label = type === 'income' ? 'Income' : type === 'transfer' ? 'Transfer' : 'Expense';
  return (
    <Badge variant={variant}>
      {label}
    </Badge>
  );
}
