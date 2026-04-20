import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Geist, Geist_Mono } from "next/font/google";
import { cn } from "@/lib/utils";
import "./globals.css";

const geistSans = Geist({
  subsets: ["latin"],
  variable: "--font-sans",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Matriosha | Sovereign Agentic Memory",
  description: "Own your data. Switch agent with no effort.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <ClerkProvider>
      <html lang="en" className="dark">
        <body className={cn(geistSans.variable, geistMono.variable, "bg-background text-foreground antialiased selection:bg-primary/30 selection:text-primary-foreground")}>
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
