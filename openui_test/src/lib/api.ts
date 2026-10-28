/**
 * fetch wrapper for calls to the FastAPI backend (via the /api rewrite).
 * A 401 means the session expired or was revoked: go back to the login page.
 */
export const authFetch: typeof fetch = async (input, init) => {
  const response = await fetch(input, { credentials: "same-origin", ...init });
  if (response.status === 401 && typeof window !== "undefined") {
    window.location.assign("/login?expired=1");
  }
  return response;
};

export type SessionUser = {
  username: string;
  display_name: string;
  role: string;
  plan?: string;
  session_expires_at?: string;
};

export async function fetchCurrentUser(): Promise<SessionUser | null> {
  const response = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (!response.ok) return null;
  const data = (await response.json()) as { user: SessionUser };
  return data.user;
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
  } finally {
    window.location.assign("/login");
  }
}

/** Error text from a FastAPI error body ({detail: {message}} or {error: {message}}). */
export async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    return body?.detail?.message ?? body?.error?.message ?? fallback;
  } catch {
    return fallback;
  }
}
