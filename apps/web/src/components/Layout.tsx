import { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  ArrowLeftRight,
  Upload,
  GitMerge,
  ScrollText,
  BarChart3,
  Wallet,
  Building2,
  Menu,
  X,
  Cpu,
  WifiOff,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { getHealth } from '../api/client';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/transactions', icon: ArrowLeftRight, label: 'Transactions' },
  { to: '/banks', icon: Building2, label: 'Banks' },
  { to: '/upload', icon: Upload, label: 'Upload Receipt' },
  { to: '/reconciliation', icon: GitMerge, label: 'Reconciliation' },
  { to: '/audit-log', icon: ScrollText, label: 'Audit Log' },
  { to: '/reports', icon: BarChart3, label: 'Reports' },
  { to: '/bank-reports', icon: Wallet, label: 'Bank Reports' },
];

export function Layout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [aiReady, setAiReady] = useState<boolean | null>(null);

  // Poll AI status every 30 s
  useEffect(() => {
    const check = () =>
      getHealth()
        .then((h) => setAiReady(h.ai.configured))
        .catch(() => setAiReady(false));
    check();
    const id = setInterval(check, 30_000);
    return () => clearInterval(id);
  }, []);

  // Close sidebar on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSidebarOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  function NavContent() {
    return (
      <>
        <div className="flex items-center gap-2 px-6 py-5 border-b">
          <Wallet className="h-6 w-6 text-primary" />
          <span className="font-bold text-lg">FinanceAudit</span>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* AI status footer */}
        <div className="px-4 py-3 border-t">
          {aiReady === null ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="h-2 w-2 rounded-full bg-muted-foreground animate-pulse" />
              Checking AI…
            </div>
          ) : aiReady ? (
            <div className="flex items-center gap-2 text-xs text-green-600">
              <Cpu className="h-3.5 w-3.5 shrink-0" />
              <span>AI ready</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-xs text-amber-600" title="Set OPENROUTER_API_KEY">
              <WifiOff className="h-3.5 w-3.5 shrink-0" />
              <span>AI not configured</span>
            </div>
          )}
        </div>
      </>
    );
  }

  return (
    <div className="flex min-h-screen bg-background">
      {/* ── Desktop sidebar (md+) ───────────────────────────────────── */}
      <aside className="hidden md:flex w-60 shrink-0 border-r bg-card flex-col">
        <NavContent />
      </aside>

      {/* ── Mobile overlay backdrop ─────────────────────────────────── */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ── Mobile slide-in sidebar ─────────────────────────────────── */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-64 bg-card border-r flex flex-col transition-transform duration-300 md:hidden',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <button
          type="button"
          className="absolute top-4 right-4 text-muted-foreground hover:text-foreground"
          onClick={() => setSidebarOpen(false)}
          aria-label="Close menu"
        >
          <X className="h-5 w-5" />
        </button>
        <NavContent />
      </aside>

      {/* ── Main content area ───────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile top bar */}
        <header className="md:hidden flex items-center gap-3 px-4 py-3 border-b bg-card sticky top-0 z-30">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-2">
            <Wallet className="h-5 w-5 text-primary" />
            <span className="font-bold">FinanceAudit</span>
          </div>
        </header>

        <main className="flex-1 overflow-auto">
          <div className="p-4 md:p-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
