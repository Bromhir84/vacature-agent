import { NavLink, Outlet } from "react-router-dom";

export default function AdminLayout() {
  return (
    <div className="admin">
      <div className="admin-bar panel">
        <div>
          <h1 style={{ margin: 0 }}>Admin</h1>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            Sources, discovery, scan runs, LLM credentials, and filter rules.
          </p>
        </div>
        <nav className="admin-nav">
          <NavLink to="/admin/sources">Sources</NavLink>
          <NavLink to="/admin/discover">Discover</NavLink>
          <NavLink to="/admin/runs">Runs</NavLink>
          <NavLink to="/admin/settings">Settings</NavLink>
          <NavLink to="/admin/filters">Filters</NavLink>
        </nav>
      </div>
      <Outlet />
    </div>
  );
}
