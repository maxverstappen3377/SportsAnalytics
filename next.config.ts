import type { NextConfig } from "next";

const INGEST_SVC_URL = process.env.INGEST_SVC_URL || "http://127.0.0.1:8001";
const ANALYTICS_SVC_URL = process.env.ANALYTICS_SVC_URL || "http://127.0.0.1:8002";
const COACH_SVC_URL = process.env.COACH_SVC_URL || "http://127.0.0.1:8003";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      // Coaching Service Routes
      {
        source: "/api/v1/matches/:match_id/coaching/:player_id",
        destination: `${COACH_SVC_URL}/api/v1/matches/:match_id/coaching/:player_id`,
      },
      {
        source: "/api/v1/coaching/refresh/:match_id",
        destination: `${COACH_SVC_URL}/api/v1/coaching/refresh/:match_id`,
      },
      // Analytics Service Routes
      {
        source: "/api/v1/matches/:match_id/trajectory",
        destination: `${ANALYTICS_SVC_URL}/api/v1/matches/:match_id/trajectory`,
      },
      {
        source: "/api/v1/matches/:match_id/analytics",
        destination: `${ANALYTICS_SVC_URL}/api/v1/matches/:match_id/analytics`,
      },
      {
        source: "/api/v1/matches/:match_id/rallies",
        destination: `${ANALYTICS_SVC_URL}/api/v1/matches/:match_id/rallies`,
      },
      {
        source: "/api/v1/matches/:match_id/report",
        destination: `${ANALYTICS_SVC_URL}/api/v1/matches/:match_id/report`,
      },
      {
        source: "/api/v1/matches/:match_id/trajectories",
        destination: `${ANALYTICS_SVC_URL}/api/v1/matches/:match_id/trajectories`,
      },
      {
        source: "/api/v1/matches/:match_id/player-positions",
        destination: `${ANALYTICS_SVC_URL}/api/v1/matches/:match_id/player-positions`,
      },
      {
        source: "/api/v1/matches/:match_id/shots",
        destination: `${ANALYTICS_SVC_URL}/api/v1/matches/:match_id/shots`,
      },
      {
        source: "/api/v1/matches/:match_id/stats/:player_id",
        destination: `${ANALYTICS_SVC_URL}/api/v1/matches/:match_id/stats/:player_id`,
      },
      {
        source: "/api/v1/matches/:match_id/heatmap",
        destination: `${ANALYTICS_SVC_URL}/api/v1/matches/:match_id/heatmap`,
      },
      {
        source: "/api/v1/rallies/:rally_id",
        destination: `${ANALYTICS_SVC_URL}/api/v1/rallies/:rally_id`,
      },
      {
        source: "/api/v1/matches/:match_id/win-probability",
        destination: `${ANALYTICS_SVC_URL}/api/v1/matches/:match_id/win-probability`,
      },
      {
        source: "/api/v1/predict/next-shot",
        destination: `${ANALYTICS_SVC_URL}/api/v1/predict/next-shot`,
      },
      {
        source: "/api/v1/rallies/:rally_id/similar",
        destination: `${ANALYTICS_SVC_URL}/api/v1/rallies/:rally_id/similar`,
      },
      // Direct video assets proxy to bypass Next.js dev server static caching
      {
        source: "/uploads/:path*",
        destination: `${INGEST_SVC_URL}/uploads/:path*`,
      },
      // Ingestion Service (default fallback for other /api/v1/ routes)
      {
        source: "/api/v1/:path*",
        destination: `${INGEST_SVC_URL}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
