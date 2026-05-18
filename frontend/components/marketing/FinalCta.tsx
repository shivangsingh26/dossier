"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { Reveal } from "@/components/motion/Reveal";
import { Button } from "@/components/ui/button";

export function FinalCta() {
  return (
    <section className="relative overflow-hidden">
      {/* Pulsing center glow */}
      <motion.div
        aria-hidden
        animate={{ opacity: [0.15, 0.28, 0.15] }}
        transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }}
        className="pointer-events-none absolute inset-x-0 top-1/2 mx-auto h-[280px] w-[640px] -translate-y-1/2 rounded-full blur-[120px]"
        style={{ background: "#f97316" }}
      />
      <div className="relative mx-auto max-w-3xl px-4 py-20 text-center sm:px-6 sm:py-24">
        <Reveal>
          <h2 className="text-3xl font-extrabold tracking-[-0.04em] text-[color:var(--color-text)] sm:text-5xl">
            Stop spamming.{" "}
            <span className="text-primary">Start applying with intent.</span>
          </h2>
        </Reveal>
        <Reveal delay={0.15}>
          <p className="mt-5 text-base text-[color:var(--color-text-muted)] sm:text-lg">
            Quality-first job search for engineers who'd rather get one warm intro
            than send fifty cold applications.
          </p>
        </Reveal>
        <Reveal delay={0.3}>
          <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
            <Button asChild size="lg" className="group/cta">
              <Link href="/sign-up">
                <span>Start free</span>
                <span className="ml-1 transition-transform group-hover/cta:translate-x-0.5">
                  →
                </span>
              </Link>
            </Button>
            <Button asChild variant="outline" size="lg">
              <Link href="/pricing">See pricing</Link>
            </Button>
          </div>
          <p className="mt-6 text-sm text-[color:var(--color-text-subtle)]">
            Free forever. 100 signup credits. No card required.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
