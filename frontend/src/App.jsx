import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import { ToastProvider } from "./components/toast.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import ReviewQueue from "./pages/ReviewQueue.jsx";
import Reconciliation from "./pages/Reconciliation.jsx";
import BankStatements from "./pages/BankStatements.jsx";
import MonthlyClose from "./pages/MonthlyClose.jsx";
import Ledger from "./pages/Ledger.jsx";
import RefundHunter from "./pages/RefundHunter.jsx";

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/reconciliation" element={<Reconciliation />} />
          <Route path="/bank-statements" element={<BankStatements />} />
          <Route path="/close" element={<MonthlyClose />} />
          <Route path="/ledger" element={<Ledger />} />
          <Route path="/refunds" element={<RefundHunter />} />
        </Route>
      </Routes>
    </ToastProvider>
  );
}
