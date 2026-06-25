import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TransactionForm } from './TransactionForm';

vi.mock('../api/client', () => ({
  getBankAccounts: vi.fn().mockResolvedValue([]),
}));

describe('TransactionForm', () => {
  it('does not reset the amount when the category is changed', async () => {
    const user = userEvent.setup();
    render(
      <TransactionForm
        defaultValues={{
          type: 'expense',
          amount: 7500.5,
          currency: 'NGN',
          category: 'Fuel Expenses',
          description: 'Existing transaction',
          date: '2026-01-15',
        }}
        onSubmit={vi.fn()}
      />
    );

    const amountInput = screen.getByPlaceholderText('0.00') as HTMLInputElement;
    expect(amountInput.value).toBe('7500.5');

    await user.click(screen.getByRole('button', { name: /Fuel Expenses/i }));
    await user.click(screen.getByText('Repairs and Maintenance'));

    expect(amountInput.value).toBe('7500.5');
  });
});
