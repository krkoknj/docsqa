import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api/* is proxied to FastAPI so the
// httpOnly session cookie is first-party. Read at build time for standalone builds.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
