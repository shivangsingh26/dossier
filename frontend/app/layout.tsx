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
          // Brand
          colorPrimary: "#f97316",
          colorDanger: "#ef4444",
          colorSuccess: "#4ade80",
          colorWarning: "#fbbf24",

          // Surfaces
          colorBackground: "#1a1410",
          colorInputBackground: "#251d18",
          colorNeutral: "#f5ebe0",

          // Text — legacy v6 names
          colorText: "#f5ebe0",
          colorTextSecondary: "#a89589",
          colorTextOnPrimaryBackground: "#1a1410",
          colorInputText: "#f5ebe0",

          // v7+ shadcn-aligned names (Clerk migrated to these)
          colorForeground: "#f5ebe0",
          colorMuted: "#251d18",
          colorMutedForeground: "#a89589",
          colorBorder: "#44342a",
          colorInput: "#251d18",
          colorInputForeground: "#f5ebe0",

          fontFamily: 'var(--font-cabinet), "Inter", system-ui, sans-serif',
          fontFamilyButtons: 'var(--font-cabinet), "Inter", system-ui, sans-serif',
          fontWeight: { normal: "400", medium: "500", semibold: "700", bold: "800" },
          borderRadius: "10px",
        },
        elements: {
          rootBox: "w-full",
          card: "bg-[#251d18] border border-[#44342a] shadow-[0_24px_60px_rgba(0,0,0,0.6)]",
          cardBox: "bg-[#251d18]",
          headerTitle: "text-[#f5ebe0]",
          headerSubtitle: "text-[#a89589]",
          formFieldLabel: "text-[#f5ebe0]",
          formFieldInput:
            "bg-[#15100d] text-[#f5ebe0] border border-[#44342a] placeholder:text-[#7a695a]",
          formFieldHintText: "text-[#a89589]",
          formButtonPrimary:
            "bg-[#f97316] hover:bg-[#ea580c] text-[#1a1410] font-semibold",
          footerActionText: "text-[#a89589]",
          footerActionLink: "text-[#f97316] hover:text-[#fdba74]",
          dividerLine: "bg-[#44342a]",
          dividerText: "text-[#7a695a]",
          socialButtonsBlockButton:
            "bg-[#15100d] text-[#f5ebe0] border border-[#44342a] hover:bg-[#1a1410]",
          socialButtonsBlockButtonText: "text-[#f5ebe0]",
          identityPreviewText: "text-[#f5ebe0]",
          identityPreviewEditButton: "text-[#f97316]",
          formResendCodeLink: "text-[#f97316]",
          otpCodeFieldInput: "bg-[#15100d] text-[#f5ebe0] border-[#44342a]",
          alertText: "text-[#f5ebe0]",
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
