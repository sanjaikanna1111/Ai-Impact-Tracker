"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Search, LayoutDashboard, Trophy, Library, MessageSquareText,
  Users, Building2, CircleDollarSign, Activity
} from "lucide-react";

const items = [
  { href: "/research", label: "Research", icon: Search, n: "01" },
  { href: "/research/overview", label: "Overview", icon: LayoutDashboard, n: "02" },
  { href: "/research/recommendations", label: "Recommendations", icon: Trophy, n: "03" },
  { href: "/research/evidence", label: "Evidence", icon: Library, n: "04" },
  { href: "/research/sentiment", label: "Sentiment", icon: MessageSquareText, n: "05" },
  { href: "/research/customers", label: "Customer impact", icon: Users, n: "06" },
  { href: "/research/financials", label: "Financials", icon: Building2, n: "07" },
  { href: "/research/value", label: "Value", icon: CircleDollarSign, n: "08" },
  { href: "/research/impact", label: "Impact tracker", icon: Activity, n: "09" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">AI</div>
          <div>
            <strong>Impact Tracker</strong>
            <span>Strategy Intelligence</span>
          </div>
        </div>

        <div className="nav-caption">RESEARCH WORKSPACE</div>
        <nav>
          {items.map(({ href, label, icon: Icon, n }) => {
            const active =
              href === "/research"
                ? pathname === href
                : pathname.startsWith(href);
            return (
              <Link key={href} href={href} className={`nav-link ${active ? "active" : ""}`}>
                <span className="nav-number">{n}</span>
                <Icon size={17} />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-note">
          <strong>Evidence first</strong>
          <span>Claims remain traceable to their source.</span>
        </div>
      </aside>

      <main className="workspace">{children}</main>
    </div>
  );
}
