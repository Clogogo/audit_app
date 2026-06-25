import { useEffect, useState } from 'react';
import { useForm, type UseFormRegister, type UseFormSetValue } from 'react-hook-form';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { CategoryCombobox } from './ui/category-combobox';
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '../api/types';
import type { TransactionCreate, TransactionType, BankAccount } from '../api/types';
import { getBankAccounts } from '../api/client';

interface TransactionFormProps {
  defaultValues?: Partial<TransactionCreate>;
  onSubmit: (data: TransactionCreate) => Promise<void>;
  onCancel?: () => void;
  isLoading?: boolean;
}

const TRANSFER_CATEGORIES = ['Internal Transfer', 'Bank Charges & Fees', 'Other'];

function getCategoriesForType(type: TransactionType): string[] {
  if (type === 'income') return INCOME_CATEGORIES;
  if (type === 'transfer') return TRANSFER_CATEGORIES;
  return EXPENSE_CATEGORIES;
}

function FieldError({ show, children }: { show?: boolean; children: string }) {
  return show ? <p className="text-xs text-destructive">{children}</p> : null;
}

// Mount-only sync of uncontrolled Select fields into react-hook-form's store.
// Extracted so its branching doesn't count toward TransactionForm's own complexity.
function syncDefaultValues(setValue: UseFormSetValue<TransactionCreate>, defaultValues?: Partial<TransactionCreate>) {
  setValue('type', defaultValues?.type ?? 'expense');
  setValue('currency', defaultValues?.currency ?? 'NGN');
  if (defaultValues?.category) setValue('category', defaultValues.category);
  if (defaultValues?.bank) setValue('bank', defaultValues.bank);
  else setValue('bank', undefined);
}

interface BankFieldProps {
  bankAccounts: BankAccount[];
  defaultValue?: string;
  onChange: (v: string | undefined) => void;
  register: UseFormRegister<TransactionCreate>;
}

function BankField({ bankAccounts, defaultValue, onChange, register }: BankFieldProps) {
  if (bankAccounts.length === 0) {
    return <Input placeholder="e.g. Access Bank" {...register('bank')} />;
  }
  const handleChange = (v: string) => onChange(v === '__none__' ? undefined : v);
  return (
    <Select defaultValue={defaultValue ?? '__none__'} onValueChange={handleChange}>
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
  );
}

export function TransactionForm({ defaultValues, onSubmit, onCancel, isLoading }: TransactionFormProps) {
  const { register, handleSubmit, watch, setValue, formState: { errors } } = useForm<TransactionCreate>({
    defaultValues: {
      type: 'expense',
      currency: 'NGN',
      date: new Date().toISOString().split('T')[0],
      ...defaultValues,
    },
  });

  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);

  useEffect(() => {
    getBankAccounts().then(setBankAccounts).catch(() => {});
  }, []);

  // Sync uncontrolled Select fields into react-hook-form store on mount
  useEffect(() => {
    syncDefaultValues(setValue, defaultValues);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const type = watch('type') as TransactionType;
  const categories = getCategoriesForType(type);

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" autoComplete="off">
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
              <SelectItem value="transfer">Transfer</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label>Amount</Label>
          <Input
            type="number"
            step="0.01"
            placeholder="0.00"
            autoComplete="off"
            data-1p-ignore
            data-lpignore="true"
            data-bwignore
            {...register('amount', { required: true, valueAsNumber: true, min: 0.01 })}
          />
          <FieldError show={!!errors.amount}>Amount is required</FieldError>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Date</Label>
          <Input type="date" {...register('date', { required: true })} />
          <FieldError show={!!errors.date}>Date is required</FieldError>
        </div>

        <div className="space-y-2">
          <Label>Currency</Label>
          <Select
            defaultValue={defaultValues?.currency ?? 'NGN'}
            onValueChange={(v) => setValue('currency', v)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="NGN">NGN (₦)</SelectItem>
              <SelectItem value="USD">USD ($)</SelectItem>
              <SelectItem value="EUR">EUR (€)</SelectItem>
              <SelectItem value="GBP">GBP (£)</SelectItem>
              <SelectItem value="JPY">JPY (¥)</SelectItem>
              <SelectItem value="CAD">CAD</SelectItem>
              <SelectItem value="AUD">AUD</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-2">
        <Label>Category</Label>
        <CategoryCombobox
          value={watch('category')}
          categories={categories}
          onChange={(v) => setValue('category', v, { shouldValidate: true })}
        />
        <FieldError show={!!errors.category}>Category is required</FieldError>
      </div>

      <div className="space-y-2">
        <Label>Bank <span className="text-muted-foreground text-xs">(optional)</span></Label>
        <BankField
          bankAccounts={bankAccounts}
          defaultValue={defaultValues?.bank}
          onChange={(v) => setValue('bank', v)}
          register={register}
        />
      </div>

      <div className="space-y-2">
        <Label>Vendor / Source</Label>
        <Input placeholder="e.g. Amazon, Acme Corp" {...register('vendor')} />
      </div>

      <div className="space-y-2">
        <Label>Description</Label>
        <Input placeholder="Brief description" {...register('description', { required: true })} />
        <FieldError show={!!errors.description}>Description is required</FieldError>
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
