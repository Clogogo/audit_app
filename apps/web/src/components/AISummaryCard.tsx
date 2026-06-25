import type { ReactNode } from 'react';
import { Sparkles } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

interface AISummaryCardProps {
  narrative: string | null;
  available: boolean;
  loading: boolean;
}

function AISummaryCardShell({ children }: { children: ReactNode }) {
  return (
    <Card className="border-secondary bg-secondary/40">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
          AI Summary
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function AISummaryCard({ narrative, available, loading }: AISummaryCardProps) {
  if (loading) {
    return (
      <AISummaryCardShell>
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
    <AISummaryCardShell>
      <p className="text-sm text-muted-foreground">{narrative}</p>
    </AISummaryCardShell>
  );
}
