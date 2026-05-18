import Link from "next/link";
import { Lockup } from "@/components/brand/Lockup";

export function MarketingFooter() {
  return (
    <footer className="border-t border-[color:var(--color-border-2)]/40 bg-[color:var(--color-surface-2)]">
      <div className="mx-auto flex max-w-6xl flex-col items-start gap-6 px-4 py-10 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <Lockup size="sm" />
        <nav className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-[color:var(--color-text-muted)]">
          <Link href="/privacy" className="hover:text-[color:var(--color-text)]">
            Privacy
          </Link>
          <Link href="/terms" className="hover:text-[color:var(--color-text)]">
            Terms
          </Link>
          <a
            href="https://github.com/shivangsingh26/dossier"
            target="_blank"
            rel="noreferrer"
            className="hover:text-[color:var(--color-text)]"
          >
            GitHub
          </a>
        </nav>
        <p className="text-xs text-[color:var(--color-text-subtle)]">
          © 2026 Dossier. Built solo.
        </p>
      </div>
    </footer>
  );
}
