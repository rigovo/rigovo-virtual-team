import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  transpilePackages: ['@rigovo/core', '@rigovo/eng'],
  experimental: {
    serverActions: {
      bodySizeLimit: '2mb',
    },
  },
};

export default nextConfig;
