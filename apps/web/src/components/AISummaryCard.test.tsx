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

  it('renders **label** markers as bold text, split into paragraphs', () => {
    const narrative = '**Financial Position:** Balance is healthy.\n**Plan:** Cut fuel spend.';
    render(<AISummaryCard narrative={narrative} available={true} loading={false} />);
    expect(screen.getByText('Financial Position:')).toBeInTheDocument();
    expect(screen.getByText('Plan:')).toBeInTheDocument();
    expect(screen.getByText(/Balance is healthy\./)).toBeInTheDocument();
    expect(screen.getByText(/Cut fuel spend\./)).toBeInTheDocument();
  });
});
