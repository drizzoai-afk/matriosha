import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata = {
  title: "Matriosha — Secure Agentic Memory",
  description: "Your sovereign digital brain.",
};

import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata = {
  title: "Matriosha — Secure Agentic Memory",
  description: "Your sovereign digital brain.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider 
      publishableKey={process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}
      afterSignOutUrl="/"
    >
      <html lang="en" className="dark">
        <body className="bg-[#080808] text-white antialiased selection:bg-cyan-500/30">{children}</body>
      </html>
    </ClerkProvider>
  );
}
