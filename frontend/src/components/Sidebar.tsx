"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, LayoutDashboard, Users, Wallet, UploadCloud } from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard", label: "数据看板", icon: LayoutDashboard },
  { href: "/creators", label: "达人库", icon: Users },
  { href: "/compensation", label: "KOL 报酬看板", icon: Wallet },
  { href: "/imports", label: "数据整理", icon: UploadCloud },
  { href: "/agent", label: "Agent 模式", icon: Bot },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <nav aria-label="主导航" className="app-sidebar" style={styles.sidebar}>
      <div style={styles.brand}>KOC 数据后台</div>
      <ul className="app-sidebar-list" style={styles.list}>
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname?.startsWith(href);
          return (
            <li key={href}>
              <Link
                href={href}
                style={{
                  ...styles.link,
                  ...(active ? styles.linkActive : {}),
                }}
              >
                <Icon size={17} />
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

const styles: Record<string, React.CSSProperties> = {
  sidebar: {
    background: "var(--color-surface)",
    borderRight: "1px solid var(--color-border)",
    display: "flex",
    flexDirection: "column",
    padding: "16px 12px",
  },
  brand: {
    fontSize: 15,
    fontWeight: 600,
    padding: "4px 8px 16px",
    color: "var(--color-text)",
  },
  list: { listStyle: "none", display: "flex", flexDirection: "column", gap: 4 },
  link: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "9px 10px",
    borderRadius: "var(--radius)",
    color: "var(--color-text-muted)",
    fontSize: 13.5,
  },
  linkActive: {
    background: "var(--color-primary-bg)",
    color: "var(--color-primary-dark)",
    fontWeight: 600,
  },
};
