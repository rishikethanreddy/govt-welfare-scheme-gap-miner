import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Routes from the previous UI keep working.
  async redirects() {
    return [
      { source: "/awareness-gaps", destination: "/dataset/analytics", permanent: false },
      { source: "/dataset-analytics", destination: "/dataset/analytics", permanent: false },
      { source: "/intents", destination: "/dataset/analytics", permanent: false },
      { source: "/explorer", destination: "/dataset/explorer", permanent: false },
      { source: "/geography", destination: "/dataset/geography", permanent: false },
      { source: "/upload", destination: "/dataset/upload", permanent: false },
      { source: "/live-scraping", destination: "/live", permanent: false },
      { source: "/live/stream", destination: "/live", permanent: false },
      { source: "/pipeline-health", destination: "/", permanent: false },
      { source: "/sources", destination: "/live/sources", permanent: false },
      { source: "/review", destination: "/", permanent: false },
      { source: "/system", destination: "/", permanent: false },
      { source: "/quality", destination: "/", permanent: false },
    ];
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "X-Frame-Options", value: "DENY" },
      ],
    }];
  },
};

export default nextConfig;
