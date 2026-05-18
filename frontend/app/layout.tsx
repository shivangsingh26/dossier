import type { Metadata } from "next";
import localFont from "next/font/local";
import { Geist_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

const cabinet = localFont({
  variable: "--font-cabinet",
  display: "swap",
  src: [
    { path: "../public/fonts/CabinetGrotesk-Regular.woff2", weight: "400", style: "normal" },
    { path: "../public/fonts/CabinetGrotesk-Medium.woff2", weight: "500", style: "normal" },
    { path: "../public/fonts/CabinetGrotesk-Bold.woff2", weight: "700", style: "normal" },
    { path: "../public/fonts/CabinetGrotesk-ExtraBold.woff2", weight: "800", style: "normal" },
  ],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Dossier — The agent prepares. You decide.",
  description:
    "Autonomous job-search intelligence. Find better jobs, reach earlier, improve every week.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <ClerkProvider
      appearance={{
        variables: {
          colorPrimary: "#f97316",
          colorBackground: "#1a1410",
          colorInputBackground: "#251d18",
          colorInputText: "#f5ebe0",
          colorText: "#f5ebe0",
          colorTextSecondary: "#a89589",
          colorNeutral: "#f5ebe0",
          colorDanger: "#ef4444",
          colorSuccess: "#4ade80",
          colorWarning: "#fbbf24",
          fontFamily: "var(--font-cabinet)",
          borderRadius: "10px",
        },
        elements: {
          card: "bg-[color:var(--color-surface)] border border-[color:var(--color-border-2)]/40 shadow-[var(--shadow-modal)]",
          headerTitle: "text-[color:var(--color-text)]",
          formButtonPrimary:
            "bg-primary hover:opacity-90 text-primary-foreground",
        },
      }}
    >
      <html
        lang="en"
        className={`${cabinet.variable} ${geistMono.variable} scroll-smooth`}
      >
        <body>{children}</body>
      </html>
    </ClerkProvider>
  );
}
