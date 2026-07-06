import { Link } from 'react-router-dom';
import {
  Wallet,
  ArrowLeftRight,
  Calculator,
  BarChart3,
  ShieldCheck,
  TrendingUp,
  TrendingDown,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { StatCard } from '../components/StatCard';

const features = [
  {
    icon: ArrowLeftRight,
    title: 'Transactions & Reconciliation',
    body: 'Record every income and expense, then reconcile bank statements automatically instead of by hand.',
  },
  {
    icon: Calculator,
    title: 'Payroll & Staff',
    body: 'Run payroll and track staff loans and advances, all tied to your school term calendar.',
  },
  {
    icon: BarChart3,
    title: 'Reports & Tax',
    body: 'Generate financial statements, CIT computations, and exportable reports in a few clicks.',
  },
  {
    icon: ShieldCheck,
    title: 'Roles & Audit Trail',
    body: 'Give each staff member exactly the access they need, with a full history of every change.',
  },
];

export function Landing() {
  return (
    <div className="min-h-[100dvh] bg-background">
      <header className="border-b">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2 text-primary">
            <Wallet className="h-6 w-6" />
            <span className="font-bold text-lg">FinanceAudit</span>
          </div>
          <Button asChild size="sm">
            <Link to="/login">Sign In</Link>
          </Button>
        </div>
      </header>

      <main>
        {/* Hero */}
        <section className="relative overflow-hidden">
          <div
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,_hsl(var(--primary)/0.08),_transparent_60%)]"
            aria-hidden="true"
          />
          <div className="max-w-6xl mx-auto px-4 py-10 md:py-14 relative grid md:grid-cols-2 gap-10 items-center">
            <div>
              <h1 className="text-4xl md:text-5xl font-bold tracking-tight leading-tight">
                One system for your school's entire financial picture.
              </h1>
              <p className="mt-4 text-base text-muted-foreground max-w-[50ch]">
                Track transactions, reconcile bank statements, run payroll, and keep a complete
                audit trail in one place.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Button asChild size="lg">
                  <Link to="/login">Sign In</Link>
                </Button>
                <Button asChild size="lg" variant="outline">
                  <Link to="/register">Create an Account</Link>
                </Button>
              </div>
            </div>

            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <StatCard title="Total Balance" amount={2450000} icon={Wallet} />
                <StatCard title="Income" amount={1500000} icon={TrendingUp} trend="up" />
                <StatCard
                  title="Expenses (This Term)"
                  amount={1250000}
                  icon={TrendingDown}
                  trend="down"
                  className="col-span-2"
                />
              </div>
              <p className="text-xs text-muted-foreground text-center">
                Sample view, not live data
              </p>
            </div>
          </div>
        </section>

        {/* Features */}
        <section className="border-t bg-secondary/30">
          <div className="max-w-6xl mx-auto px-4 py-16 md:py-20">
            <h2 className="text-2xl md:text-3xl font-bold text-center">
              Everything your finance office needs
            </h2>
            <div className="mt-10 grid sm:grid-cols-2 gap-4">
              {features.map(({ icon: Icon, title, body }) => (
                <Card
                  key={title}
                  className="transition-transform hover:-translate-y-0.5"
                >
                  <CardHeader className="flex flex-row items-center gap-3 space-y-0 pb-2">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <Icon className="h-5 w-5" />
                    </div>
                    <CardTitle className="text-base">{title}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground">{body}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* Closing CTA */}
        <section className="border-t">
          <div className="max-w-6xl mx-auto px-4 py-16 text-center">
            <h2 className="text-2xl md:text-3xl font-bold">Ready when you are.</h2>
            <p className="mt-2 text-muted-foreground">
              Sign in to your account to get started.
            </p>
            <div className="mt-6">
              <Button asChild size="lg">
                <Link to="/login">Sign In</Link>
              </Button>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t py-6">
        <p className="text-center text-xs text-muted-foreground">
          © {new Date().getFullYear()} FinanceAudit. All rights reserved.
        </p>
      </footer>
    </div>
  );
}
