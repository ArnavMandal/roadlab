import type { NextConfig } from "next";
const config: NextConfig = {
  outputFileTracingRoot: process.cwd(),
  turbopack: { root: process.cwd() },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.RELAY_URL || "http://127.0.0.1:8080"}/:path*`,
      },
    ];
  },
};
export default config;
