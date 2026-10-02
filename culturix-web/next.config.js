/** @type {import('next').NextConfig} */
const nextConfig = {
  // The creator product pages were retired when the public site became viewer-only; old links land
  // on the homepage instead of a 404.
  async redirects() {
    return [{ source: "/products/:path*", destination: "/", permanent: true }];
  },
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
