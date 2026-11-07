import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/shell";

export const metadata: Metadata = { title: "QuoteIQ — procurement intelligence", description: "From vendor quotations to confident procurement decisions." };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body><Providers>{children}</Providers></body>
    </html>
  );
}
