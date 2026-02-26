import { Loader2 } from 'lucide-react';

interface LoadingStateProps {
  message?: string;
  fullScreen?: boolean;
}

export function LoadingState({ message = 'Loading...', fullScreen = false }: LoadingStateProps) {
  const content = (
    <div className="flex flex-col items-center justify-center gap-3">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <p className="text-muted-foreground">{message}</p>
    </div>
  );

  if (fullScreen) {
    return <div className="flex items-center justify-center min-h-screen">{content}</div>;
  }

  return <div className="py-12">{content}</div>;
}

// Skeleton loaders
export function SkeletonCard() {
  return <div className="h-32 bg-muted animate-pulse rounded-lg" />;
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-16 bg-muted animate-pulse rounded" />
      ))}
    </div>
  );
}
