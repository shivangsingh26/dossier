"use client";

import { motion, useInView } from "motion/react";
import { useRef, type ReactNode } from "react";

type RevealProps = {
  children: ReactNode;
  delay?: number;
  className?: string;
  /** vertical pixel offset from which content rises */
  from?: number;
};

/**
 * Wraps any element in a single fade + rise animation that fires once
 * when it scrolls into view. Used everywhere on the marketing page
 * to give a Linear-style "everything settles in place" feel.
 */
export function Reveal({
  children,
  delay = 0,
  className,
  from = 14,
}: RevealProps) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: from }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ delay, duration: 0.55, ease: [0.21, 0.5, 0.21, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}
