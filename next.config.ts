import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  turbopack: {
    rules: {
      '*.ts': {
        as: '*.ts',
      },
    },
  },
  // Ignora la cartella edge-functions che è per Supabase/Deno
  experimental: {
    outputFileTracingExcludes: {
      '*': ['./edge-functions/**/*'],
    },
  },
  webpack: (config) => {
    config.module.rules.push({
      test: /\.ts$/,
      include: /edge-functions/,
      loader: 'ignore-loader',
    });
    return config;
  },
};

export default nextConfig;
