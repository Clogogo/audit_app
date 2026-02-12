import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '../api/types';
import type { TransactionCreate, TransactionType, BankAccount } from '../api/types';
import { getBankAccounts } from '../api/client';

interface TransactionFormProps {
  defaultValues?: Partial<TransactionCreate>;
  onSubmit: (data: TransactionCreate) => Promise<void>;
  onCancel?: () => void;
  isLoading?: boolean;
}

export function TransactionForm({ defaultValues, onSubmit, onCancel, isLoading }: TransactionFormProps) {
  const { register, handleSubmit, watch, setValue, formState: { errors } } = useForm<TransactionCreate>({
    defaultValues: {
      type: 'expense',
      currency: 'USD',
      date: new Date().toISOString().split('T')[0],
      ...defaultValues,
    },
  });

  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);

  useEffect(() => {
    getBankAccounts().then(setBankAccounts).catch(() => {});
  }, []);

  const type = watch('type') as TransactionType;
  const categories = type === 'income' ? INCOME_CATEGORIES : EXPENSE_CATEGORIES;

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Type</Label>
          <Select
            defaultValue={defaultValues?.type ?? 'expense'}
            onValueChange={(v) => setValue('type', v as TransactionType)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="expense">Expense</SelectItem>
              <SelectItem value="income">Income</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label>Amount</Label>
          <Input
            type="number"
            step="0.01"
            placeholder="0.00"
            {...register('amount', { required: true, valueAsNumber: true, min: 0.01 })}
          />
          {errors.amount && <p className="text-xs text-destructive">Amount is required</p>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Date</Label>
          <Input type="date" {...register('date', { required: true })} />
          {errors.date && <p className="text-xs text-destructive">Date is required</p>}
        </div>

        <div className="space-y-2">
          <Label>Currency</Label>
          <Select
            defaultValue={defaultValues?.currency ?? 'USD'}
            onValueChange={(v) => setValue('currency', v)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="USD">USD</SelectItem>
              <SelectItem value="EUR">EUR</SelectItem>
              <SelectItem value="GBP">GBP</SelectItem>
              <SelectItem value="JPY">JPY</SelectItem>
              <SelectItem value="CAD">CAD</SelectItem>
              <SelectItem value="AUD">AUD</SelectItem>
              <SelectItem value="NGN">NGN</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-2">
        <Label>Category</Label>
        <Select
          defaultValue={defaultValues?.category}
          onValueChange={(v) => setValue('category', v)}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select category" />
          </SelectTrigger>
          <SelectContent>
            {categories.map((c) => (
              <SelectItem key={c} value={c}>{c}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.category && <p className="text-xs text-destructive">Category is required</p>}
      </div>

      <div className="space-y-2">
        <Label>Bank <span className="text-muted-foreground text-xs">(optional)</span></Label>
        {bankAccounts.length > 0 ? (
          <Select
            defaultValue={defaultValues?.bank ?? '__none__'}
            onValueChange={(v) => setValue('bank', v === '__none__' ? undefined : v)}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select bank" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">None</SelectItem>
              {bankAccounts.map((b) => (
                <SelectItem key={b.id} value={b.bank_name}>
                  {b.bank_name}{b.account_number ? ` — ${b.account_number}` : ''}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input placeholder="e.g. Access Bank" {...register('bank')} />
        )}
      </div>

      <div className="space-y-2">
        <Label>Vendor / Source</Label>
        <Input placeholder="e.g. Amazon, Acme Corp" {...register('vendor')} />
      </div>

      <div className="space-y-2">
        <Label>Description</Label>
        <Input placeholder="Brief description" {...register('description', { required: true })} />
        {errors.description && <p className="text-xs text-destructive">Description is required</p>}
      </div>

      <div className="flex justify-end gap-2 pt-2">
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={isLoading}>
          {isLoading ? 'Saving...' : 'Save Transaction'}
        </Button>
      </div>
    </form>
  );
}
