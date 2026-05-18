"use client";

import Link from "next/link";
import { motion, useScroll, useTransform } from "motion/react";
import { useRef } from "react";
import { Mark } from "@/components/brand/Mark";
import { Button } from "@/components/ui/button";

export function HeroSection() {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollY } = useScroll();
  const glowY = useTransform(scrollY, [0, 600], [0, 90]);

  return (
    <section ref={ref} className="relative overflow-hidden">
      {/* Single warm-peach glow, contained, low opacity */}
      <motion.div
        aria-hidden
        style={{ y: glowY, background: "#f97316" }}
        className="pointer-events-none absolute -top-40 left-1/2 h-[360px] w-[720px] -translate-x-1/2 rounded-full opacity-15 blur-[120px]"
      />

      <div className="relative mx-auto flex max-w-5xl flex-col items-center px-4 pt-14 pb-16 text-center sm:px-6 sm:pt-20 sm:pb-24">
        <motion.span
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.21, 0.5, 0.21, 1] }}
          className="mb-7 inline-flex items-center gap-2 rounded-full border border-[color:var(--color-border-2)]/60 bg-[color:var(--color-surface)]/60 px-3 py-1 text-xs text-[color:var(--color-text-muted)] backdrop-blur"
        >
          <span aria-hidden className="text-primary">⚡</span>
          Agentic — runs while you sleep
        </motion.span>

        <motion.div
          initial={{ opacity: 0, scale: 0.92 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.55, delay: 0.05, ease: [0.21, 0.5, 0.21, 1] }}
          className="mb-8"
        >
          <Mark size={56} />
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.12, ease: [0.21, 0.5, 0.21, 1] }}
          className="max-w-3xl text-[clamp(2.75rem,6.5vw,5rem)] font-extrabold leading-[0.98] tracking-[-0.045em] text-[color:var(--color-text)]"
        >
          The agent prepares.
          <br />
          <span className="text-primary">You decide.</span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.22, ease: [0.21, 0.5, 0.21, 1] }}
          className="mt-5 max-w-xl text-base text-[color:var(--color-text-muted)] sm:text-lg"
        >
          Autonomous job-search intelligence. Seven agents find the right roles,
          research the company, draft your resume, and find your referral.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.32, ease: [0.21, 0.5, 0.21, 1] }}
          className="mt-8 flex flex-wrap items-center justify-center gap-3"
        >
          <Button asChild size="lg" className="group/cta">
            <Link href="/sign-up">
              <span>Start free</span>
              <span className="ml-1 transition-transform group-hover/cta:translate-x-0.5">
                →
              </span>
            </Link>
          </Button>
          <Button asChild variant="outline" size="lg">
            <Link href="#how-it-works">See how it works</Link>
          </Button>
        </motion.div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.5 }}
          className="mt-5 text-xs text-[color:var(--color-text-subtle)]"
        >
          Free forever · 100 signup credits · No card
        </motion.p>
      </div>
    </section>
  );
}
