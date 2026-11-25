import type { NextRequest } from "next/server";

/**
 * Forwards every /api/* request to the FastAPI backend.
 *
 * This replaces the old next.config rewrite, which baked BACKEND_URL in at
 * build time. Reading it per request lets the same build run locally
 * (127.0.0.1:8000) and on Cloudflare Workers (a `BACKEND_URL` Worker var).
 * Request bodies (small JSON) are buffered so the backend gets a Content-Length;
 * response bodies are streamed so SSE chat answers stay unbuffered.
 */
export const dynamic = "force-dynamic";

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

function backendBase(): string {
  return (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

async function forward(request: NextRequest): Promise<Response> {
  const incoming = new URL(request.url);
  const target = `${backendBase()}${incoming.pathname}${incoming.search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  headers.set("x-forwarded-host", incoming.host);
  headers.set("x-forwarded-proto", incoming.protocol.replace(":", ""));

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
    });
  } catch (error) {
    return Response.json(
      { detail: `Backend unreachable at ${backendBase()}: ${(error as Error).message}` },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "content-encoding") {
      responseHeaders.append(key, value);
    }
  });
  // Set-Cookie must survive as separate headers (Headers.forEach joins them).
  const cookies = upstream.headers.getSetCookie?.() ?? [];
  if (cookies.length) {
    responseHeaders.delete("set-cookie");
    for (const cookie of cookies) responseHeaders.append("set-cookie", cookie);
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
export const OPTIONS = forward;
export const HEAD = forward;
