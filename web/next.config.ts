import type { NextConfig } from "next";

// UI → FastAPI は localhost 同居前提（docs/designs/web-ui-architecture.md §2）。
// /api/* を rewrites で API プロセスへプロキシし、ブラウザ側は相対パスで
// fetch / EventSource できるようにする（CORS 不要・Server/Client で URL 共通）。
// 接続先は API_PROXY_TARGET で差し替え可能（既定: 127.0.0.1:8000）。
const apiTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiTarget}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
