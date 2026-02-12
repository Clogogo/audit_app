import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from '../components/Layout';
import { Dashboard } from '../pages/Dashboard';
import { Transactions } from '../pages/Transactions';
import { Upload } from '../pages/Upload';
import { Reconciliation } from '../pages/Reconciliation';
import { AuditLog } from '../pages/AuditLog';
import { Reports } from '../pages/Reports';
import { Banks } from '../pages/Banks';

export function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/reconciliation" element={<Reconciliation />} />
          <Route path="/audit-log" element={<AuditLog />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/banks" element={<Banks />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
