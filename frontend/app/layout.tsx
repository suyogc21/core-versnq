import type { Metadata, Viewport } from "next";
import { Geist_Mono, Inter } from "next/font/google";

import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Versnq Core",
  description: "Leads, follow-ups and customers in one place",
  appleWebApp: { capable: true, title: "Versnq", statusBarStyle: "default" }, // installable (C2)
  icons: { apple: "/apple-icon.png" },
};

export const viewport: Viewport = { themeColor: "#1d1d1f" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full text-[13px]">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
