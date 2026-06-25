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
    expect(screen.getByText('AI Summary')).toBeInTheDocument();
  });
});
