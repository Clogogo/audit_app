import type { ReactNode } from 'react';
import { Sparkles } from 'lucide-react';
import { cn } from '../lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

interface AISummaryCardProps {
  narrative: string | null;
  available: boolean;
  loading: boolean;
  // Extra classes for the outer Card — lets callers slot it into a column.
  className?: string;
  // Cap height and scroll instead of growing — for narrow sidebar columns.
  compact?: boolean;
}

function AISummaryCardShell({
  children,
  className,
  compact,
}: {
  children: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <Card className={cn('border-secondary bg-secondary/40', className)}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
          AI Financial Analysis
        </CardTitle>
      </CardHeader>
      <CardContent className={cn(compact && 'max-h-[22rem] overflow-y-auto pr-1')}>
        {children}
      </CardContent>
    </Card>
  );
}

// The prompt asks the model for **Label:** paragraphs separated by a blank
// line — render those bold markers instead of showing the raw asterisks,
// without pulling in a full markdown dependency for this one pattern.
// Splitting on blank lines (not every newline) keeps a section intact even
// if the model soft-wraps a single paragraph across lines.
function renderNarrative(narrative: string) {
  const paragraphs = narrative
    .split(/\r?\n\s*\r?\n+/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  return paragraphs.map((paragraph, i) => {
    const parts = paragraph.split('**');
    return (
      <p key={i} className="text-sm text-muted-foreground">
        {parts.map((part, j) =>
          j % 2 === 1 ? <strong key={j} className="text-foreground">{part}</strong> : part
        )}
      </p>
    );
  });
}

export function AISummaryCard({
  narrative,
  available,
  loading,
  className,
  compact,
}: AISummaryCardProps) {
  if (loading) {
    return (
      <AISummaryCardShell className={className} compact={compact}>
        <div className="space-y-2 animate-pulse">
          <div className="h-3 bg-muted rounded w-full" />
          <div className="h-3 bg-muted rounded w-5/6" />
          <div className="h-3 bg-muted rounded w-2/3" />
        </div>
      </AISummaryCardShell>
    );
  }

  if (!available) {
    return null;
  }

  if (!narrative) {
    return null;
  }

  return (
    <AISummaryCardShell className={className} compact={compact}>
      <div className="space-y-3">{renderNarrative(narrative)}</div>
    </AISummaryCardShell>
  );
}
