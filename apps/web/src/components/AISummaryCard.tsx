import { Sparkles } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

interface AISummaryCardProps {
  narrative: string | null;
  available: boolean;
  loading: boolean;
}

export function AISummaryCard({ narrative, available, loading }: AISummaryCardProps) {
  if (!loading && (!available || !narrative)) {
    return null;
  }

  return (
    <Card className="border-secondary bg-secondary/40">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          AI Summary
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-2 animate-pulse">
            <div className="h-3 bg-muted rounded w-full" />
            <div className="h-3 bg-muted rounded w-5/6" />
            <div className="h-3 bg-muted rounded w-2/3" />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{narrative}</p>
        )}
      </CardContent>
    </Card>
  );
}
