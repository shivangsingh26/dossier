"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { Reveal } from "@/components/motion/Reveal";
import { Button } from "@/components/ui/button";

type MiniTier = {
  name: string;
  price: string;
  credits: string;
  blurb: string;
  highlight?: boolean;
};

const TIERS: MiniTier[] = [
  {
    name: "Lite",
    price: "₹0",
    credits: "50 cr / mo",
    blurb: "Job discovery only. Free forever.",
  },
  {
    name: "Pro",
    price: "₹999",
    credits: "500 cr / mo",
    blurb: "+ Watchlist, intel, gap analysis.",
    highlight: true,
  },
  {
    name: "Max",
    price: "₹2,999",
    credits: "2,000 cr / mo",
    blurb: "+ Resume, cover letter, referrals, market intel.",
  },
];

export function PricingTeaser() {
  return (
    <section className="border-t border-[color:var(--color-border-2)]/30 bg-[color:var(--color-surface-2)]/40">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-extrabold tracking-[-0.035em] text-[color:var(--color-text)] sm:text-4xl">
            Pay only when you act.
          </h2>
          <p className="mt-3 text-base text-[color:var(--color-text-muted)]">
            Credits track every agent invocation. No subscriptions hide unused
            capacity.
          </p>
        </Reveal>

        <div className="mx-auto mt-12 grid max-w-4xl gap-4 sm:grid-cols-3">
          {TIERS.map((tier, i) => (
            <Reveal key={tier.name} delay={i * 0.08}>
              <motion.div
                whileHover={{ y: -4 }}
                transition={{ duration: 0.2 }}
                className={
                  tier.highlight
                    ? "rounded-xl border border-primary/60 bg-[color:var(--color-surface)] p-5 shadow-[var(--shadow-hover)]"
                    : "rounded-xl border border-[color:var(--color-border-2)]/40 bg-[color:var(--color-surface)] p-5 transition-colors hover:border-primary/40"
                }
              >
                <div className="flex items-baseline justify-between">
                  <h3 className="text-lg font-bold tracking-[-0.02em] text-[color:var(--color-text)]">
                    {tier.name}
                  </h3>
                  <span
                    className="text-2xl text-[color:var(--color-text)] tabular-nums"
                    style={{ fontFamily: "var(--font-geist-mono)" }}
                  >
                    {tier.price}
                  </span>
                </div>
                <p
                  className="mt-1 text-xs text-secondary"
                  style={{ fontFamily: "var(--font-geist-mono)" }}
                >
                  {tier.credits}
                </p>
                <p className="mt-3 text-sm text-[color:var(--color-text-muted)]">
                  {tier.blurb}
                </p>
              </motion.div>
            </Reveal>
          ))}
        </div>

        <Reveal delay={0.35} className="mt-10 flex justify-center">
          <Button asChild variant="outline">
            <Link href="/pricing">See full pricing →</Link>
          </Button>
        </Reveal>
      </div>
    </section>
  );
}
