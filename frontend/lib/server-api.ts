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
  return fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: token ? `Bearer ${token}` : "",
    },
    cache: "no-store",
  });
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
  if (res.status === 403) return { kind: "no-account" };
  if (!res.ok) {
    return { kind: "error", status: res.status, message: await res.text() };
  }
  const account = (await res.json()) as Account;
  return { kind: "ok", account };
}
