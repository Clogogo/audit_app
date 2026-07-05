import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AISummaryCard } from './AISummaryCard';

describe('AISummaryCard', () => {
  it('renders the narrative when available', () => {
    render(<AISummaryCard narrative="Expenses rose this month." available={true} loading={false} />);
    expect(screen.getByText('Expenses rose this month.')).toBeInTheDocument();
  });

  it('renders nothing when unavailable', () => {
    const { container } = render(<AISummaryCard narrative={null} available={false} loading={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a loading placeholder while fetching', () => {
    render(<AISummaryCard narrative={null} available={false} loading={true} />);
    expect(screen.getByText('AI Financial Analysis')).toBeInTheDocument();
  });

  it('renders **label** markers as <strong> elements, split into separate paragraphs', () => {
    const narrative = '**Financial Position:** Balance is healthy.\n**Plan:** Cut fuel spend.';
    const { container } = render(<AISummaryCard narrative={narrative} available={true} loading={false} />);

    const financialLabel = screen.getByText('Financial Position:');
    const planLabel = screen.getByText('Plan:');
    expect(financialLabel.tagName).toBe('STRONG');
    expect(planLabel.tagName).toBe('STRONG');

    const paragraphs = container.querySelectorAll('p');
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0].textContent).toBe('Financial Position: Balance is healthy.');
    expect(paragraphs[1].textContent).toBe('Plan: Cut fuel spend.');
  });
});
