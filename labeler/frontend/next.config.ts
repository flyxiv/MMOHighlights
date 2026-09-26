import type { NextConfig } from "next";

const backendUrl = (process.env.BACKEND_URL ?? "http://localhost:8100").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  // Uploads go through the /api proxy; the page also batches them under this size.
  experimental: { middlewareClientMaxBodySize: "64mb" },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
