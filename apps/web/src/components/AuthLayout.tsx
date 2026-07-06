import type { ReactNode } from 'react';
import { Wallet } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';

interface AuthLayoutProps {
  title: string;
  description: string;
  children: ReactNode;
  footer?: ReactNode;
}

// Shared shell for Login/Register/ForgotPassword/ResetPassword: a single
// on-brand background (teal wash from the app's own tokens, not a generic
// slate gradient) instead of four copies that could drift apart.
export function AuthLayout({ title, description, children, footer }: AuthLayoutProps) {
  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-background relative overflow-hidden p-4">
      <div
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,_hsl(var(--primary)/0.10),_transparent_60%)]"
        aria-hidden="true"
      />
      <Card className="w-full max-w-md relative">
        <CardHeader className="space-y-3">
          <div className="flex items-center justify-center gap-2 text-primary mb-2">
            <Wallet className="h-10 w-10" />
            <h1 className="text-3xl font-bold">FinanceAudit</h1>
          </div>
          <CardTitle className="text-center">{title}</CardTitle>
          <CardDescription className="text-center">{description}</CardDescription>
        </CardHeader>
        <CardContent>
          {children}
          {footer && <div className="text-center text-sm text-muted-foreground mt-4">{footer}</div>}
        </CardContent>
      </Card>
    </div>
  );
}
