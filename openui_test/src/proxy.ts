import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE = process.env.SESSION_COOKIE_NAME ?? "qc_session";

/**
 * Optimistic check only: send visitors without a session cookie to /login.
 * FastAPI validates the session on every API call and is the real authority.
 */
export function proxy(request: NextRequest) {
  const hasSession = Boolean(request.cookies.get(SESSION_COOKIE)?.value);
  const isAuthPage = ["/login", "/signup"].includes(request.nextUrl.pathname);

  if (!hasSession && !isAuthPage) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Pages only: API calls are proxied to FastAPI, which returns 401 itself.
  matcher: ["/((?!api/|_next/|favicon|icon|logos/|.*\.svg$).*)"],
};
