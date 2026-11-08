import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar.jsx";
import { READ_ONLY } from "../lib/api.js";

export default function Layout() {
  return (
    <div className="app">
      <Sidebar />
      <main className="main">
        {READ_ONLY ? (
          <div className="demo-banner" role="status">
            <b>Read-only demo with invented data.</b> Nothing here is anyone's real spending, and changes
            are turned off. To try uploads, matching and Ask, run the app locally.
          </div>
        ) : null}
        <Outlet />
      </main>
    </div>
  );
}
