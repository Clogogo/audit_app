import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { NotificationProvider } from '../hooks';
import { AuthProvider } from '../contexts/AuthContext';
import { ProtectedRoute } from '../components/ProtectedRoute';
import { Layout } from '../components/Layout';
import { Login } from '../pages/Login';
import { Register } from '../pages/Register';
import { ForgotPassword } from '../pages/ForgotPassword';
import { ResetPassword } from '../pages/ResetPassword';
import { Dashboard } from '../pages/Dashboard';
import { Transactions } from '../pages/Transactions';
import { Upload } from '../pages/Upload';
import { Reconciliation } from '../pages/Reconciliation';
import { AuditLog } from '../pages/AuditLog';
import { Reports } from '../pages/Reports';
import { Banks } from '../pages/Banks';
import BankAccountReports from '../pages/BankAccountReports';
import { Tax } from '../pages/Tax';
import { FinancialStatements } from '../pages/FinancialStatements';
import { Assets } from '../pages/Assets';
import { TaxCalendar } from '../pages/TaxCalendar';
import { StaffLoans } from '../pages/StaffLoans';
import { StaffDirectory } from '../pages/StaffDirectory';
import { Payroll } from '../pages/Payroll';
import { Terms } from '../pages/Terms';
import { SchoolLoans } from '../pages/SchoolLoans';

export function App() {
  return (
    <NotificationProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />

            {/* Protected routes */}
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/transactions" element={<Transactions />} />
                      <Route path="/upload" element={<Upload />} />
                      <Route path="/reconciliation" element={<Reconciliation />} />
                      <Route path="/audit-log" element={<AuditLog />} />
                      <Route path="/reports" element={<Reports />} />
                      <Route path="/bank-reports" element={<BankAccountReports />} />
                      <Route path="/banks" element={<Banks />} />
                      <Route path="/tax" element={<Tax />} />
                      <Route path="/tax/financial-statements" element={<FinancialStatements />} />
                      <Route path="/tax/assets" element={<Assets />} />
                      <Route path="/tax/calendar" element={<TaxCalendar />} />
                      <Route path="/tax/school-loans" element={<SchoolLoans />} />
                      <Route path="/staff/directory" element={<StaffDirectory />} />
                      <Route path="/staff/loans" element={<StaffLoans />} />
                      <Route path="/staff/payroll" element={<Payroll />} />
                      <Route path="/staff/terms" element={<Terms />} />
                    </Routes>
                  </Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </NotificationProvider>
  );
}

export default App;
