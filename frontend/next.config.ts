import type { NextConfig } from "next";
import withSerwistInit from "@serwist/next";

const withSerwist = withSerwistInit({
  swSrc: "src/sw.ts",
  swDest: "public/sw.js",
  // Disable in dev — registered only in production builds
  disable: process.env.NODE_ENV === "development",
  // Automatically register the SW via @serwist/next injected script
  register: false, // we register manually to guard NODE_ENV
});

const nextConfig: NextConfig = {
  output: "standalone",
};

export default withSerwist(nextConfig);
