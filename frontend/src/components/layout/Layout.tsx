import React from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";

export const Layout: React.FC = () => {
  return (
    <div className="app-layout" data-testid="app-shell">
      <Sidebar />
      <div className="main-wrapper">
        <Header />
        <main className="page-container" role="main">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
