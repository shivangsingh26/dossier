// Client-side fetch helpers (React Server Components: use server-api.ts).
// useApi() returns a thin fetch wrapper that injects the Clerk session token.
"use client";

import { useAuth } from "@clerk/nextjs";
import type { Account } from "./server-api";

export type { Account } from "./server-api";

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export function useApi() {
  const { getToken } = useAuth();

  async function authedFetch(path: string, init?: RequestInit): Promise<Response> {
    const token = await getToken();
    return fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.headers ?? {}),
        Authorization: token ? `Bearer ${token}` : "",
      },
    });
  }

  return {
    getMe: async (): Promise<Account> => {
      const r = await authedFetch("/me");
      if (!r.ok) throw new Error(`/me failed: ${r.status}`);
      return r.json();
    },
  };
}
