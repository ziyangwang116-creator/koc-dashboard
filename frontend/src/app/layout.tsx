import type { Metadata } from "next";
import "./globals.css";
import { AppProviders } from "@/lib/providers";

export const metadata: Metadata = {
  title: "KOC 数据后台",
  description: "内部数据运营只读看板",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN">
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
