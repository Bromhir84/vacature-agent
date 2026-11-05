import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import ListingsPage from "./pages/Listings";
import SourcesPage from "./pages/Sources";
import RunsPage from "./pages/Runs";
import AdminLayout from "./pages/admin/AdminLayout";
import AdminSettingsPage from "./pages/admin/AdminSettings";
import AdminFiltersPage from "./pages/admin/AdminFilters";
import AdminDiscoverPage from "./pages/admin/AdminDiscover";
import "./App.css";

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Vacature Agent</div>
        <nav>
          <NavLink to="/" end>
            Listings
          </NavLink>
          <NavLink to="/admin">Admin</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<ListingsPage />} />
          <Route path="/sources" element={<Navigate to="/admin/sources" replace />} />
          <Route path="/runs" element={<Navigate to="/admin/runs" replace />} />
          <Route path="/settings" element={<Navigate to="/admin/settings" replace />} />
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<Navigate to="settings" replace />} />
            <Route path="settings" element={<AdminSettingsPage />} />
            <Route path="filters" element={<AdminFiltersPage />} />
            <Route path="sources" element={<SourcesPage />} />
            <Route path="discover" element={<AdminDiscoverPage />} />
            <Route path="runs" element={<RunsPage />} />
          </Route>
        </Routes>
      </main>
    </div>
  );
}
