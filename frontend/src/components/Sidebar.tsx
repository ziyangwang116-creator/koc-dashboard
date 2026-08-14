"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  ChartNoAxesCombined,
  Database,
  LayoutDashboard,
  UploadCloud,
  Users,
  Wallet,
  X,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard", label: "数据看板", icon: LayoutDashboard },
  { href: "/creators", label: "达人库", icon: Users },
  { href: "/compensation", label: "KOL 报酬看板", icon: Wallet },
  { href: "/imports", label: "数据整理", icon: UploadCloud },
  { href: "/agent", label: "Agent 模式", icon: Bot },
];

export function Sidebar({
  open = false,
  onClose,
}: {
  open?: boolean;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  return (
    <nav aria-label="主导航" className={`app-sidebar${open ? " is-open" : ""}`}>
      <div className="sidebar-brand">
        <span className="sidebar-brand-mark"><Database size={17} /></span>
        <span>
          <strong>KOC Console</strong>
          <small>内容运营后台</small>
        </span>
        <button type="button" className="sidebar-close" onClick={onClose} aria-label="关闭导航">
          <X size={17} />
        </button>
      </div>
      <div className="sidebar-section-label">工作台</div>
      <ul className="app-sidebar-list">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname?.startsWith(href);
          return (
            <li key={href}>
              <Link
                href={href}
                className={`sidebar-link${active ? " sidebar-link-active" : ""}`}
                onClick={onClose}
              >
                <Icon size={17} />
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="sidebar-footer">
        <ChartNoAxesCombined size={15} />
        <span>KOC 数据运营</span>
      </div>
    </nav>
  );
}
