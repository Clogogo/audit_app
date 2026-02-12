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
} from 'lucide-react';
import { cn } from '../lib/utils';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/transactions', icon: ArrowLeftRight, label: 'Transactions' },
  { to: '/banks', icon: Building2, label: 'Banks' },
  { to: '/upload', icon: Upload, label: 'Upload Receipt' },
  { to: '/reconciliation', icon: GitMerge, label: 'Reconciliation' },
  { to: '/audit-log', icon: ScrollText, label: 'Audit Log' },
  { to: '/reports', icon: BarChart3, label: 'Reports' },
];

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r bg-card flex flex-col">
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
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="p-8">{children}</div>
      </main>
    </div>
  );
}
