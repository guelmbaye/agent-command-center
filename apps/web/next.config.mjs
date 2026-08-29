/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone", // image Cloud Run minimale
  env: {
    NEXT_PUBLIC_ACC_API: process.env.NEXT_PUBLIC_ACC_API ?? "http://localhost:8080",
  },
};

export default nextConfig;
