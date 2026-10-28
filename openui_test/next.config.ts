import type { NextConfig } from "next";

// The browser only ever talks to this Next.js origin. Every /api/* call is
// forwarded to the FastAPI backend, which owns authentication, routing,
// MongoDB access and all API keys.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  // Next 16.3 + Vercel's adapter skips next-server.js.nft.json when standalone
  // is on; Vercel ignores standalone anyway. Keep it for Docker / self-host.
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),
  // Keep streamed (SSE) chat responses unbuffered through the rewrite.
  compress: false,
  turbopack: {
    root: process.cwd(),
  },
  experimental: {
    turbopackMinify: false,
    // Chat answers can take longer than the 30 s default proxy timeout.
    proxyTimeout: 180_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "Permissions-Policy", value: "microphone=(self), camera=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
