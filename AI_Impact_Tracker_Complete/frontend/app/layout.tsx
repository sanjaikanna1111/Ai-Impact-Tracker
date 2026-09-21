import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Impact Tracker",
  description: "Evidence-based AI strategy and impact measurement",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}