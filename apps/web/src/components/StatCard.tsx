import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { formatCurrency } from '../lib/utils';
import type { LucideIcon } from 'lucide-react';

interface StatCardProps {
  title: string;
  amount: number;
  currency?: string;
  icon: LucideIcon;
  trend?: 'up' | 'down' | 'neutral';
  className?: string;
}

export function StatCard({ title, amount, currency = 'NGN', icon: Icon, trend, className }: StatCardProps) {
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div
          className={`text-2xl font-bold ${
            trend === 'up' ? 'text-green-600' : trend === 'down' ? 'text-red-600' : ''
          }`}
        >
          {formatCurrency(amount, currency)}
        </div>
      </CardContent>
    </Card>
  );
}
