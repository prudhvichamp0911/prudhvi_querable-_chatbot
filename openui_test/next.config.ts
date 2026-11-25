import type { NextConfig } from "next";

// The browser only ever talks to this Next.js origin. Every /api/* call is
// forwarded to the FastAPI backend by src/app/api/[...path]/route.ts, which
// reads BACKEND_URL per request (works locally and on Cloudflare Workers).

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  // Next 16.3 + Vercel's adapter skips next-server.js.nft.json when standalone
  // is on; Vercel ignores standalone anyway. Keep it for Docker / self-host.
  // OpenNext (Cloudflare) also needs standalone output, so this stays on there.
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),
  // Keep streamed (SSE) chat responses unbuffered through the /api proxy.
  compress: false,
  turbopack: {
    root: process.cwd(),
  },
  experimental: {
    // Minify on Cloudflare builds: unminified server code exceeds the Workers size limit.
    turbopackMinify: process.env.CLOUDFLARE_BUILD === "1",
    // Chat answers can take longer than the 30 s default proxy timeout.
    proxyTimeout: 180_000,
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
