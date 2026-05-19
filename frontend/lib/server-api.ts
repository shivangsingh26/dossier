// Server-only helpers for calling the FastAPI backend from React Server Components.
// Uses the Clerk session token; throws on non-2xx.
import { auth } from "@clerk/nextjs/server";

export type Account = {
  user_id: string;
  clerk_id: string;
  email: string;
  data_user_slug: string;
  role: "user" | "admin";
  tier: "lite" | "pro" | "max";
  status: "pending" | "active" | "suspended";
  credits: number;
  credits_reset_at: string;
  created_at: string;
  last_login_at: string | null;
};

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

async function authedFetch(path: string, init?: RequestInit): Promise<Response> {
  const { getToken } = await auth();
  const token = await getToken();
  const headers: Record<string, string> = { ...(init?.headers as Record<string, string> ?? {}) };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return fetch(`${BASE}${path}`, { ...init, headers, cache: "no-store" });
}

export type MeResult =
  | { kind: "ok"; account: Account }
  | { kind: "no-account" }
  | { kind: "error"; status: number; message: string };

export async function fetchMe(): Promise<MeResult> {
  let res: Response;
  try {
    res = await authedFetch("/me");
  } catch (e) {
    return { kind: "error", status: 0, message: (e as Error).message };
  }
  // 401 = no/empty Clerk JWT (session token not yet issued on first RSC render
  // after fresh signup). 403 = JWT valid but no accounts.db row yet (webhook
  // hasn't fired) or account suspended. UX-wise both are "pending / not ready"
  // — render the pending screen instead of an error.
  if (res.status === 401 || res.status === 403) return { kind: "no-account" };
  if (!res.ok) {
    return { kind: "error", status: res.status, message: await res.text() };
  }
  const account = (await res.json()) as Account;
  return { kind: "ok", account };
}

export async function fetchPersonaState(): Promise<{ synthesized: boolean } | null> {
  let res: Response;
  try {
    res = await authedFetch("/persona/state");
  } catch {
    return null;
  }
  if (!res.ok) return null;
  return res.json();
}
