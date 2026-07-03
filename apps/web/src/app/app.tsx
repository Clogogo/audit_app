import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { NotificationProvider } from '../hooks';
import { AuthProvider } from '../contexts/AuthContext';
import { ProtectedRoute } from '../components/ProtectedRoute';
import { PermissionRoute } from '../components/PermissionRoute';
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
import { AdvancePayments } from '../pages/AdvancePayments';
import { StaffDirectory } from '../pages/StaffDirectory';
import { Payroll } from '../pages/Payroll';
import { Terms } from '../pages/Terms';
import { SchoolLoans } from '../pages/SchoolLoans';
import { UserManagement } from '../pages/UserManagement';
import { RoleManagement } from '../pages/RoleManagement';

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
                      {/* Dashboard stays universal — any active logged-in user
                          lands here regardless of role, even one with zero
                          section permissions granted. */}
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/transactions" element={<PermissionRoute permission="transactions"><Transactions /></PermissionRoute>} />
                      <Route path="/upload" element={<PermissionRoute permission="banking"><Upload /></PermissionRoute>} />
                      <Route path="/reconciliation" element={<PermissionRoute permission="banking"><Reconciliation /></PermissionRoute>} />
                      <Route path="/audit-log" element={<PermissionRoute permission="audit_log"><AuditLog /></PermissionRoute>} />
                      <Route path="/reports" element={<PermissionRoute permission="banking"><Reports /></PermissionRoute>} />
                      <Route path="/bank-reports" element={<PermissionRoute permission="banking"><BankAccountReports /></PermissionRoute>} />
                      <Route path="/banks" element={<PermissionRoute permission="banking"><Banks /></PermissionRoute>} />
                      <Route path="/tax" element={<PermissionRoute permission="tax"><Tax /></PermissionRoute>} />
                      <Route path="/tax/financial-statements" element={<PermissionRoute permission="tax"><FinancialStatements /></PermissionRoute>} />
                      <Route path="/tax/assets" element={<PermissionRoute permission="tax"><Assets /></PermissionRoute>} />
                      <Route path="/tax/calendar" element={<PermissionRoute permission="tax"><TaxCalendar /></PermissionRoute>} />
                      <Route path="/tax/school-loans" element={<PermissionRoute permission="tax"><SchoolLoans /></PermissionRoute>} />
                      <Route path="/staff/directory" element={<PermissionRoute permission="staff"><StaffDirectory /></PermissionRoute>} />
                      <Route path="/staff/loans" element={<PermissionRoute permission="staff"><StaffLoans /></PermissionRoute>} />
                      <Route path="/staff/advances" element={<PermissionRoute permission="staff"><AdvancePayments /></PermissionRoute>} />
                      <Route path="/staff/payroll" element={<PermissionRoute permission="staff"><Payroll /></PermissionRoute>} />
                      <Route path="/staff/terms" element={<PermissionRoute permission="staff"><Terms /></PermissionRoute>} />
                      <Route path="/user-management" element={<PermissionRoute permission="user_management"><UserManagement /></PermissionRoute>} />
                      <Route path="/role-management" element={<PermissionRoute permission="user_management"><RoleManagement /></PermissionRoute>} />
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
