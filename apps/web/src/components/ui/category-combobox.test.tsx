import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CategoryCombobox } from './category-combobox';

const CATEGORIES = ['Fuel Expenses', 'Bank Charges', 'Repairs and Maintenance'];

describe('CategoryCombobox', () => {
  it('calls onChange with the selected category', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<CategoryCombobox value={undefined} categories={CATEGORIES} onChange={onChange} />);

    await user.click(screen.getByRole('button'));
    await user.click(screen.getByText('Bank Charges'));

    expect(onChange).toHaveBeenCalledWith('Bank Charges');
  });

  it('filters the list when typing in the search box', async () => {
    const user = userEvent.setup();
    render(<CategoryCombobox value={undefined} categories={CATEGORIES} onChange={vi.fn()} />);

    await user.click(screen.getByRole('button'));
    await user.type(screen.getByPlaceholderText('Search categories…'), 'fuel');

    expect(screen.getByText('Fuel Expenses')).toBeInTheDocument();
    expect(screen.queryByText('Bank Charges')).not.toBeInTheDocument();
  });
});
