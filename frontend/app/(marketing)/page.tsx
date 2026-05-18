import Link from "next/link";
import { Mark } from "@/components/brand/Mark";
import { Button } from "@/components/ui/button";

export default function HeroPage() {
  return (
    <section className="relative mx-auto flex max-w-6xl flex-col items-center px-4 py-20 text-center sm:px-6 sm:py-28 lg:py-36">
      <Mark size={72} className="mb-8" />

      <h1
        className="max-w-4xl text-[clamp(2.25rem,6vw,4.5rem)] leading-[1.05] tracking-tight"
        style={{ fontFamily: "var(--font-fraunces)" }}
      >
        <span className="italic font-medium">The agent prepares.</span>
        <br />
        <span className="font-medium">You decide.</span>
      </h1>

      <p className="mt-6 max-w-2xl text-base text-[color:var(--color-text-muted)] sm:text-lg">
        Dossier is your autonomous job-search intelligence. It finds the right roles,
        researches the company, drafts your resume, and finds your referral —
        so every application is your best shot.
      </p>

      <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
        <Button asChild size="lg">
          <Link href="/sign-up">Start free →</Link>
        </Button>
        <Button asChild variant="outline" size="lg">
          <Link href="/pricing">Watch a run</Link>
        </Button>
      </div>

      <p className="mt-6 text-sm text-[color:var(--color-text-subtle)]">
        Free forever. 100 signup credits. No card.
      </p>
    </section>
  );
}
