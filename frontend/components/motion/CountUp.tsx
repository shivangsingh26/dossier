"use client";

import { animate, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";

type CountUpProps = {
  to: number;
  duration?: number;
  className?: string;
  /** appended after the number, e.g. "%" or "+" */
  suffix?: string;
};

/**
 * Tweens a number from 0 → `to` when scrolled into view.
 * Used for the job score badge and pricing prices.
 */
export function CountUp({ to, duration = 1.2, className, suffix }: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const [n, setN] = useState(0);

  useEffect(() => {
    if (!inView) return;
    const controls = animate(0, to, {
      duration,
      ease: [0.21, 0.5, 0.21, 1],
      onUpdate: (v) => setN(Math.round(v)),
    });
    return () => controls.stop();
  }, [inView, to, duration]);

  return (
    <span ref={ref} className={className}>
      {n}
      {suffix}
    </span>
  );
}
