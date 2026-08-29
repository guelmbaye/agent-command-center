import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ACC — Autonomous Mission Control",
  description:
    "Control plane for governed, recoverable autonomous enterprise missions.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
