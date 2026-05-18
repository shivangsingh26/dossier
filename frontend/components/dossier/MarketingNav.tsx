import Link from "next/link";
import { Lockup } from "@/components/brand/Lockup";
import { Button } from "@/components/ui/button";

export function MarketingNav() {
  return (
    <header className="sticky top-0 z-30 w-full border-b border-[color:var(--color-border-2)]/40 bg-[color:var(--color-bg)]/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" aria-label="Dossier home">
          <Lockup size="sm" />
        </Link>
        <nav className="flex items-center gap-2 sm:gap-4">
          <Link
            href="/pricing"
            className="hidden text-sm text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)] sm:inline"
          >
            Pricing
          </Link>
          <Link
            href="/sign-in"
            className="text-sm text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]"
          >
            Sign in
          </Link>
          <Button asChild size="sm">
            <Link href="/sign-up">Start free</Link>
          </Button>
        </nav>
      </div>
    </header>
  );
}
