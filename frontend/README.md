# frontend — Dossier Next.js 16 SaaS web app

Empty placeholder. Implementation starts in **M1** — see `docs/superpowers/milestones/M1.md`.

## Planned contents

- Next.js 16 App Router with TypeScript strict mode
- Tailwind v4 + shadcn/ui + motion + AI Elements (chat-style persona quiz)
- Clerk authentication (user + admin roles, free tier 10K MAU)
- Marketing pages: `/` (hero), `/pricing` (3-tier)
- Auth pages: `/sign-in`, `/sign-up` (themed)
- App pages: `/dashboard`, `/onboarding` (M3), `/jobs` (M4), `/admin` (M5), …
- Brand: warm mocha theme + Split-D mark + Fraunces italic wordmark

## Setup (in M1)

```bash
cd frontend && pnpm create next-app . --typescript --app --tailwind
pnpm add @clerk/nextjs @tanstack/react-query motion react-hook-form zod
pnpm dlx shadcn-ui@latest init
```

Run:

```bash
pnpm dev   # http://localhost:3000
```

## Cost

Free. Vercel hobby tier (when deployed) — see spec §5.
