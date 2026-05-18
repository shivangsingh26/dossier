/**
 * Typed re-exports of design tokens for use in TS (motion variants,
 * inline-style edge cases, tests). Keep in sync with globals.css @theme.
 */
export const theme = {
  color: {
    bg: "#1a1410",
    surface: "#251d18",
    surface2: "#15100d",
    border: "#2d2419",
    border2: "#44342a",
    text: "#f5ebe0",
    textMuted: "#a89589",
    textSubtle: "#7a695a",
    primary: "#f97316",
    primaryHov: "#ea580c",
    primarySoft: "#fdba74",
    secondary: "#4ade80",
    secondarySoft: "rgba(74, 222, 128, 0.15)",
    warning: "#fbbf24",
    danger: "#ef4444",
  },
  font: {
    sans: "var(--font-geist)",
    mono: "var(--font-geist-mono)",
  },
} as const;

export type Theme = typeof theme;
