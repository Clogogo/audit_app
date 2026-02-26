import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { NotificationProvider } from '../hooks';
import { AuthProvider } from '../contexts/AuthContext';
import { ProtectedRoute } from '../components/ProtectedRoute';
import { Layout } from '../components/Layout';
import { Login } from '../pages/Login';
// import { Register } from '../pages/Register'; // Registration temporarily hidden
import { Dashboard } from '../pages/Dashboard';
import { Transactions } from '../pages/Transactions';
import { Upload } from '../pages/Upload';
import { Reconciliation } from '../pages/Reconciliation';
import { AuditLog } from '../pages/AuditLog';
import { Reports } from '../pages/Reports';
import { Banks } from '../pages/Banks';
import BankAccountReports from '../pages/BankAccountReports';

export function App() {
  return (
    <NotificationProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<Login />} />
            {/* Registration temporarily hidden */}
            {/* <Route path="/register" element={<Register />} /> */}

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
