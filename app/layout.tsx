import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";

const geist = Geist({subsets:['latin'],variable:'--font-sans'});

export const metadata = {
  title: "Matriosha — Secure Agentic Memory",
  description: "Your sovereign digital brain.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en" className={cn("dark", "font-sans", geist.variable)}>
        <body className="bg-[#080808] text-white antialiased selection:bg-cyan-500/30">{children}</body>
      </html>
    </ClerkProvider>
  );
}
