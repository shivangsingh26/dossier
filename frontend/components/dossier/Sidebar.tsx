"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserButton } from "@clerk/nextjs";
import { Lockup } from "@/components/brand/Lockup";

type NavItem = {
  href: string;
  label: string;
  tier?: "pro" | "max";
};

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/jobs", label: "Jobs" },
  { href: "/watchlist", label: "Watchlist", tier: "pro" },
  { href: "/gaps", label: "Gaps", tier: "pro" },
  { href: "/resume", label: "Resume", tier: "max" },
  { href: "/referrals", label: "Referrals", tier: "max" },
  { href: "/market", label: "Market", tier: "max" },
  { href: "/settings", label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-[color:var(--color-border-2)]/40 bg-[color:var(--color-surface-2)] px-4 py-6 md:flex">
      <Link href="/dashboard" className="mb-8 inline-block" aria-label="Dossier home">
        <Lockup size="sm" />
      </Link>

      <nav className="flex flex-1 flex-col gap-1">
        {NAV.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center justify-between rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-[color:var(--color-surface)] text-[color:var(--color-text)]"
                  : "text-[color:var(--color-text-muted)] hover:bg-[color:var(--color-surface)] hover:text-[color:var(--color-text)]"
              }`}
            >
              <span>{item.label}</span>
              {item.tier && (
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
                    item.tier === "pro"
                      ? "bg-secondary/15 text-secondary"
                      : "bg-primary/15 text-primary"
                  }`}
                  style={{ fontFamily: "var(--font-geist-mono)" }}
                >
                  {item.tier}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto pt-6">
        <UserButton
          appearance={{ elements: { avatarBox: "h-8 w-8" } }}
        />
      </div>
    </aside>
  );
}
