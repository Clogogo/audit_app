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
    // The prompt asks for a blank line between sections — matching that
    // contract here, not a single \n, since the renderer only splits on
    // blank lines (see the next test for why a single \n must NOT split).
    const narrative = '**Financial Position:** Balance is healthy.\n\n**Plan:** Cut fuel spend.';
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

  it('does not split a single section on a soft-wrapped newline', () => {
    const narrative = '**Financial Position:** Balance is healthy,\nwith income exceeding expenses.';
    const { container } = render(<AISummaryCard narrative={narrative} available={true} loading={false} />);

    const paragraphs = container.querySelectorAll('p');
    expect(paragraphs).toHaveLength(1);
  });

  it('applies className to the root Card', () => {
    const { container } = render(
      <AISummaryCard narrative="Expenses rose." available={true} loading={false} className="lg:col-span-2" />
    );
    expect(container.firstElementChild).toHaveClass('lg:col-span-2');
  });

  it('caps height and scrolls in compact mode, without stretching to fill its container', () => {
    const { container } = render(
      <AISummaryCard narrative="Expenses rose." available={true} loading={false} compact />
    );
    const content = container.querySelector('.max-h-\\[22rem\\]');
    expect(content).toBeInTheDocument();
    expect(content).toHaveClass('overflow-y-auto');
    // compact must cap height, not stretch full-height (that would reintroduce
    // the empty-space bug this component exists to avoid in a grid/flex row).
    expect(container.firstElementChild).not.toHaveClass('h-full');
  });
});
