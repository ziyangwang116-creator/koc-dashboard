import type { NextConfig } from "next";

// Server-side only env var (never exposed to the browser bundle). Used to proxy
// same-origin /api/* requests to a local FastAPI instance during development.
const API_PROXY_TARGET = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_PROXY_TARGET}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
