/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    return [
      {
        source: "/backend/:path*",
        destination: `${api}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
