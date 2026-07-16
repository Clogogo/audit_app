import { useState, useEffect } from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  ArrowLeftRight,
  Upload,
  GitMerge,
  ScrollText,
  BarChart3,
  Wallet,
  Building2,
  Calculator,
  CalendarClock,
  Building,
  Package,
  Menu,
  X,
  LogOut,
  User,
  ChevronDown,
  ChevronRight,
  Users,
  CreditCard,
  Landmark,
  CalendarRange,
  HandCoins,
  Banknote,
  ShieldCheck,
  Shield,
  Lock,
  Boxes,
  ClipboardList,
  History,
  FileBarChart,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useAuth } from '../contexts/AuthContext';
import { hasPermission } from '../lib/permissions';
import { Button } from './ui/button';
import { ThemeToggle } from './ThemeToggle';

const topNavItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/transactions', icon: ArrowLeftRight, label: 'Transactions' },
];

const bankingSubItems = [
  { to: '/banks', icon: Building2, label: 'Bank Accounts' },
  { to: '/upload', icon: Upload, label: 'Import Statement' },
  { to: '/reconciliation', icon: GitMerge, label: 'Reconciliation' },
  { to: '/reports', icon: BarChart3, label: 'Reports' },
  { to: '/bank-reports', icon: Wallet, label: 'Bank Reports' },
];

const bottomNavItems = [
  { to: '/audit-log', icon: ScrollText, label: 'Audit Log' },
];

const taxSubItems = [
  { to: '/tax', icon: Calculator, label: 'CIT (Nigeria)' },
  { to: '/tax/financial-statements', icon: Building, label: 'Financial Statements' },
  { to: '/tax/assets', icon: Package, label: 'Asset Register' },
  { to: '/tax/school-loans', icon: HandCoins, label: 'School Loans' },
  { to: '/tax/calendar', icon: CalendarClock, label: 'Tax Calendar' },
];

const staffSubItems = [
  { to: '/staff/directory', icon: Users, label: 'Staff Directory' },
  { to: '/staff/loans', icon: CreditCard, label: 'Staff Loans' },
  { to: '/staff/advances', icon: Banknote, label: 'Advance Payment (IOU)' },
  { to: '/staff/payroll', icon: Calculator, label: 'Payroll' },
  { to: '/staff/terms', icon: CalendarRange, label: 'Terms' },
];

const inventorySubItems = [
  { to: '/inventory/items', icon: Boxes, label: 'Items' },
  { to: '/inventory/requests', icon: ClipboardList, label: 'Stock Requests' },
  { to: '/inventory/movements', icon: History, label: 'Stock Movements' },
  { to: '/inventory/reports', icon: FileBarChart, label: 'Report' },
];

const accessSubItems = [
  { to: '/user-management', icon: ShieldCheck, label: 'User Management' },
  { to: '/role-management', icon: Shield, label: 'Role Management' },
];

export function Layout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const visibleTopNavItems = topNavItems.filter(
    ({ to }) => to === '/' || hasPermission(user, 'transactions')
  );

  const canManageUsers = hasPermission(user, 'user_management');
  const visibleBottomNavItems = hasPermission(user, 'audit_log') ? bottomNavItems : [];

  const isTaxActive = location.pathname.startsWith('/tax');
  const isStaffActive = location.pathname.startsWith('/staff');
  const isBankingActive = ['/banks', '/upload', '/reconciliation', '/reports', '/bank-reports'].some(
    (p) => location.pathname === p
  );
  const isAccessActive = ['/user-management', '/role-management'].includes(location.pathname);
  const isInventoryActive = location.pathname.startsWith('/inventory');
  const [taxOpen, setTaxOpen] = useState(isTaxActive);
  const [staffOpen, setStaffOpen] = useState(isStaffActive);
  const [bankingOpen, setBankingOpen] = useState(isBankingActive);
  const [accessOpen, setAccessOpen] = useState(isAccessActive);
  const [inventoryOpen, setInventoryOpen] = useState(isInventoryActive);

  // Auto-expand sections when on their routes
  useEffect(() => {
    if (isTaxActive) setTaxOpen(true);
  }, [isTaxActive]);

  useEffect(() => {
    if (isStaffActive) setStaffOpen(true);
  }, [isStaffActive]);

  useEffect(() => {
    if (isBankingActive) setBankingOpen(true);
  }, [isBankingActive]);

  useEffect(() => {
    if (isAccessActive) setAccessOpen(true);
  }, [isAccessActive]);

  useEffect(() => {
    if (isInventoryActive) setInventoryOpen(true);
  }, [isInventoryActive]);

  const handleLogout = () => {
    logout();
    navigate('/');
  };

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
          {visibleTopNavItems.map(({ to, icon: Icon, label }) => (
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

          {/* Banking section — collapsible */}
          {hasPermission(user, 'banking') && (
          <div>
            <button
              type="button"
              onClick={() => setBankingOpen((v) => !v)}
              className={cn(
                'w-full flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isBankingActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground'
              )}
            >
              <Landmark className="h-4 w-4 shrink-0" />
              <span className="flex-1 text-left">Banking</span>
              {bankingOpen
                ? <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
            </button>

            {bankingOpen && (
              <div className="ml-4 mt-1 space-y-0.5 border-l border-border/50 pl-3">
                {bankingSubItems.map(({ to, icon: Icon, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    onClick={() => setSidebarOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-primary text-primary-foreground'
                          : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                      )
                    }
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    {label}
                  </NavLink>
                ))}
              </div>
            )}
          </div>
          )}

          {/* Tax section — collapsible parent */}
          {hasPermission(user, 'tax') && (
          <div>
            <button
              type="button"
              onClick={() => setTaxOpen((v) => !v)}
              className={cn(
                'w-full flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isTaxActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground'
              )}
            >
              <Calculator className="h-4 w-4 shrink-0" />
              <span className="flex-1 text-left">Tax</span>
              {taxOpen
                ? <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
            </button>

            {taxOpen && (
              <div className="ml-4 mt-1 space-y-0.5 border-l border-border/50 pl-3">
                {taxSubItems.map(({ to, icon: Icon, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={to === '/tax'}
                    onClick={() => setSidebarOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-primary text-primary-foreground'
                          : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                      )
                    }
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    {label}
                  </NavLink>
                ))}
              </div>
            )}
          </div>
          )}

          {/* Staff section — collapsible parent */}
          {hasPermission(user, 'staff') && (
          <div>
            <button
              type="button"
              onClick={() => setStaffOpen((v) => !v)}
              className={cn(
                'w-full flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isStaffActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground'
              )}
            >
              <Users className="h-4 w-4 shrink-0" />
              <span className="flex-1 text-left">Staff</span>
              {staffOpen
                ? <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
            </button>

            {staffOpen && (
              <div className="ml-4 mt-1 space-y-0.5 border-l border-border/50 pl-3">
                {staffSubItems.map(({ to, icon: Icon, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    onClick={() => setSidebarOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-primary text-primary-foreground'
                          : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                      )
                    }
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    {label}
                  </NavLink>
                ))}
              </div>
            )}
          </div>
          )}

          {/* Inventory section — collapsible parent */}
          {hasPermission(user, 'inventory') && (
          <div>
            <button
              type="button"
              onClick={() => setInventoryOpen((v) => !v)}
              className={cn(
                'w-full flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isInventoryActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground'
              )}
            >
              <Package className="h-4 w-4 shrink-0" />
              <span className="flex-1 text-left">Inventory</span>
              {inventoryOpen
                ? <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
            </button>

            {inventoryOpen && (
              <div className="ml-4 mt-1 space-y-0.5 border-l border-border/50 pl-3">
                {inventorySubItems.map(({ to, icon: Icon, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    onClick={() => setSidebarOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-primary text-primary-foreground'
                          : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                      )
                    }
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    {label}
                  </NavLink>
                ))}
              </div>
            )}
          </div>
          )}

          {/* Access section — collapsible parent */}
          {canManageUsers && (
          <div>
            <button
              type="button"
              onClick={() => setAccessOpen((v) => !v)}
              className={cn(
                'w-full flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isAccessActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground'
              )}
            >
              <Lock className="h-4 w-4 shrink-0" />
              <span className="flex-1 text-left">Access</span>
              {accessOpen
                ? <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
            </button>

            {accessOpen && (
              <div className="ml-4 mt-1 space-y-0.5 border-l border-border/50 pl-3">
                {accessSubItems.map(({ to, icon: Icon, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    onClick={() => setSidebarOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-primary text-primary-foreground'
                          : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                      )
                    }
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    {label}
                  </NavLink>
                ))}
              </div>
            )}
          </div>
          )}

          {/* Bottom standalone items */}
          {visibleBottomNavItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
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

        {/* User info and logout */}
        <div className="px-4 py-3 border-t bg-muted/20">
          <div className="flex items-center gap-3 mb-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
              <User className="h-4 w-4" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{user?.full_name || 'User'}</p>
              <p className="text-xs text-muted-foreground truncate">{user?.email}</p>
            </div>
            <ThemeToggle />
          </div>
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={handleLogout}
          >
            <LogOut className="h-3.5 w-3.5 mr-2" />
            Logout
          </Button>
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
          <div className="flex items-center gap-2 flex-1">
            <Wallet className="h-5 w-5 text-primary" />
            <span className="font-bold">FinanceAudit</span>
          </div>
          <ThemeToggle />
        </header>

        <main className="flex-1 overflow-auto">
          <div className="p-4 md:p-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
