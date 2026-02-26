import { useState } from 'react';
import { Plus, Trash2, Building2, CreditCard, Pencil, Search } from 'lucide-react';
import { getBankAccounts, createBankAccount, updateBankAccount, deleteBankAccount } from '../api/client';
import type { BankAccount, BankAccountCreate } from '../api/types';
import { useAsync, useNotification } from '../hooks';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { ConfirmDialog } from '../components/ConfirmDialog';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from '../components/ui/dialog';
import { Card, CardContent } from '../components/ui/card';

export function Banks() {
  const notify = useNotification();
  const { data: accounts, loading, refetch } = useAsync(getBankAccounts);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [form, setForm] = useState<BankAccountCreate>({
    bank_name: '',
    account_holder_name: '',
    account_number: '',
  });
  const [error, setError] = useState('');

  // Confirm delete
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<BankAccount | null>(null);
  const [deleting, setDeleting] = useState(false);

  const filteredAccounts = (accounts || []).filter((account) => {
    const q = searchQuery.toLowerCase();
    return (
      account.bank_name.toLowerCase().includes(q) ||
      account.account_holder_name?.toLowerCase().includes(q) ||
      account.account_number?.toLowerCase().includes(q)
    );
  });

  const handleSave = async () => {
    if (!form.bank_name.trim()) {
      setError('Bank name is required');
      return;
    }
    setSaving(true);
    setError('');
    try {
      if (editing) {
        await updateBankAccount(editing, form);
        notify.success('Bank account updated');
      } else {
        await createBankAccount(form);
        notify.success('Bank account created');
      }
      setForm({ bank_name: '', account_holder_name: '', account_number: '' });
      setEditing(null);
      setDialogOpen(false);
      refetch();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Failed to save bank account');
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (account: BankAccount) => {
    setEditing(account.id);
    setForm({
      bank_name: account.bank_name,
      account_holder_name: account.account_holder_name || '',
      account_number: account.account_number || '',
    });
    setDialogOpen(true);
  };

  const askDelete = (account: BankAccount) => {
    setDeleteTarget(account);
    setConfirmOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteBankAccount(deleteTarget.id);
      notify.success('Bank account deleted');
    } catch (err: any) {
      notify.error(err.message || 'Failed to delete account');
    } finally {
      setDeleting(false);
      setConfirmOpen(false);
      setDeleteTarget(null);
      refetch();
    }
  };

  const resetDialog = () => {
    setDialogOpen(false);
    setEditing(null);
    setForm({ bank_name: '', account_holder_name: '', account_number: '' });
    setError('');
  };

  return (
    <div className="space-y-6">
      <ConfirmDialog
        open={confirmOpen}
        title="Delete bank account?"
        description={`Remove "${deleteTarget?.bank_name}${deleteTarget?.account_number ? ` (${deleteTarget.account_number})` : ''}" from your saved accounts. This does not affect existing transactions.`}
        confirmLabel="Delete"
        loading={deleting}
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmOpen(false)}
      />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Bank Accounts</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage bank accounts and set holder names to identify internal transfers
          </p>
        </div>

        <Dialog open={dialogOpen} onOpenChange={(o) => { if (!o) resetDialog(); else setDialogOpen(o); }}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4" />
              Add Bank Account
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {editing ? <><Pencil className="h-5 w-5 text-blue-600" />Edit Bank Account</> : <><Plus className="h-5 w-5" />New Bank Account</>}
              </DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <Label>Bank Name <span className="text-destructive">*</span></Label>
                <Input
                  placeholder="e.g. Access Bank, GTBank, First Bank"
                  value={form.bank_name}
                  onChange={(e) => setForm({ ...form, bank_name: e.target.value })}
                  onKeyDown={(e) => e.key === 'Enter' && handleSave()}
                />
              </div>
              <div className="space-y-2">
                <Label>Account Holder Name <span className="text-muted-foreground text-xs">(helps identify internal transfers)</span></Label>
                <Input
                  placeholder="e.g. COMPANY LTD"
                  value={form.account_holder_name}
                  onChange={(e) => setForm({ ...form, account_holder_name: e.target.value })}
                  onKeyDown={(e) => e.key === 'Enter' && handleSave()}
                />
              </div>
              <div className="space-y-2">
                <Label>Account Number <span className="text-muted-foreground text-xs">(optional)</span></Label>
                <Input
                  placeholder="e.g. 0123456789"
                  value={form.account_number}
                  onChange={(e) => setForm({ ...form, account_number: e.target.value })}
                  onKeyDown={(e) => e.key === 'Enter' && handleSave()}
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={resetDialog}>Cancel</Button>
              <Button onClick={handleSave} disabled={!form.bank_name.trim() || saving}>
                {saving ? 'Saving…' : editing ? 'Update Account' : 'Save Account'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Search */}
      {(accounts?.length || 0) > 0 && (
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search accounts..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
          {searchQuery && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
              {filteredAccounts.length} result{filteredAccounts.length !== 1 ? 's' : ''}
            </div>
          )}
        </div>
      )}

      {loading ? (
        <div className="text-center py-16 text-muted-foreground">Loading...</div>
      ) : filteredAccounts.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground">
          <Building2 className="h-12 w-12 mx-auto mb-4 opacity-30" />
          <p className="font-medium">{searchQuery ? 'No matching accounts' : 'No bank accounts saved yet'}</p>
          <p className="text-sm mt-1">
            {searchQuery ? `Try adjusting "${searchQuery}"` : 'Add an account to use it as a quick-select when importing statements.'}
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filteredAccounts.map((acc) => (
            <Card key={acc.id} className="group">
              <CardContent className="flex items-center gap-4 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10">
                  <Building2 className="h-5 w-5 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">{acc.bank_name}</p>
                  {acc.account_holder_name && (
                    <p className="text-xs text-muted-foreground truncate mt-0.5">
                      {acc.account_holder_name}
                    </p>
                  )}
                  {acc.account_number && (
                    <p className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5">
                      <CreditCard className="h-3 w-3" />
                      {acc.account_number}
                    </p>
                  )}
                  {!acc.account_holder_name && !acc.account_number && (
                    <p className="text-xs text-muted-foreground mt-0.5">No details</p>
                  )}
                </div>
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleEdit(acc)}
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => askDelete(acc)}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
