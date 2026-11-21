import {
  ArrowLeftRight, Banknote, BookOpen, Building, Calculator, FileText, HandCoins, Layers, type LucideIcon,
  Package, Percent, Receipt, Scale, ShoppingCart, TrendingUp, UserMinus, Users, Wallet,
} from 'lucide-react';

export interface ReportCard { key: string; title: string; description: string; icon: LucideIcon; to: string; permission?: string }
export interface ReportGroup { title: string; hint: string; reports: ReportCard[] }

const FS = '/tax/financial-statements';   // the statements page already holds these
const AR = '/tax/accounting-reports';
const hub = (slug: string) => `/financial-reports/${slug}`;

export const REPORT_GROUPS: ReportGroup[] = [
  { title: 'Financial statements', hint: 'The formal accounts', reports: [
    { key: 'full', title: 'Full Financial Statements', description: 'Every statement together in one document, ready to send', icon: FileText, to: FS },
    { key: 'trial-balance', title: 'Trial Balance', description: 'Every account and its closing balance', icon: Scale, to: AR },
    { key: 'profit-loss', title: 'Profit & Loss', description: 'What you earned and what you spent', icon: TrendingUp, to: AR },
    { key: 'balance-sheet', title: 'Balance Sheet', description: 'What you own and what you owe today', icon: Building, to: FS },
    { key: 'cash-flow', title: 'Cash Flow', description: 'Where the money came from and where it went', icon: ArrowLeftRight, to: FS },
    { key: 'equity', title: 'Changes in Equity', description: "How the owners' share of the business moved", icon: Layers, to: FS },
    { key: 'notes', title: 'Notes to the Account (Accounting Policies)', description: 'The detail sitting behind each figure', icon: BookOpen, to: FS },
  ] },
  { title: 'Everyday reports', hint: 'Day-to-day checks', reports: [
    { key: 'who-owes-you', title: 'Who Owes You', description: 'Staff loans and salary advances still to be repaid, by age', icon: Users, to: hub('who-owes-you'), permission: 'staff' },
    { key: 'who-you-owe', title: 'Who You Owe', description: 'Loans still to be repaid, by age', icon: UserMinus, to: hub('who-you-owe') },
    { key: 'sales', title: 'Sales Report', description: 'What you sold, and how that has moved', icon: ShoppingCart, to: hub('sales') },
    { key: 'expenses', title: 'Expense Report', description: 'Everything you spent, broken down', icon: Receipt, to: hub('expenses') },
    { key: 'payroll', title: 'Payroll Summary', description: 'What you paid your staff and what was deducted', icon: Wallet, to: hub('payroll-summary'), permission: 'staff' },
    { key: 'assets', title: 'Asset Register', description: 'Everything you own and what it is worth now', icon: Package, to: '/tax/assets' },
  ] },
  { title: 'Tax', hint: 'Returns you file', reports: [
    { key: 'vat', title: 'VAT Return', description: 'The VAT you owe or can claim back (estimate)', icon: Percent, to: hub('vat') },
    { key: 'paye', title: 'PAYE Return', description: 'Tax taken from your staff pay (estimate)', icon: Banknote, to: hub('paye'), permission: 'staff' },
    { key: 'cit', title: 'Company Income Tax', description: 'Your yearly company tax return', icon: Calculator, to: '/tax' },
    { key: 'pit', title: 'Personal Income Tax', description: "Tax on directors' pay (estimate)", icon: Users, to: hub('personal-income-tax') },
    { key: 'wht', title: 'Withholding Tax', description: 'Tax you should hold back when paying suppliers (estimate)', icon: HandCoins, to: hub('withholding-tax') },
    { key: 'capital-allowances', title: 'Capital Allowances', description: 'The relief you get on equipment and property', icon: Building, to: hub('capital-allowances') },
  ] },
];

const RECENT_KEY = 'financial-reports:recent';
const safe = <T,>(fn: () => T, fallback: T): T => { try { return fn(); } catch { return fallback; } };

export function recentReportKeys(): string[] {
  return safe(() => JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]') as string[], []);
}

export function rememberReport(key: string): void {
  safe(() => localStorage.setItem(RECENT_KEY, JSON.stringify([key, ...recentReportKeys().filter((k) => k !== key)].slice(0, 3))), undefined);
}
