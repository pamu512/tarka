import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import { DashboardLayout } from "@/components/DashboardLayout";
import "./globals.css";

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Tarka-UI",
  description: "Rule Engine vs. Shadow AI — forensic console",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistMono.variable} h-full`}>
      <body className="h-full min-h-dvh bg-slate-950 font-mono text-slate-200 antialiased">
        <DashboardLayout>{children}</DashboardLayout>
      </body>
    </html>
  );
}
