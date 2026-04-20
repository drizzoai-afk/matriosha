import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata = {
  title: "Matriosha — Secure Agentic Memory",
  description: "Your sovereign digital brain.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const pk = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  
  if (!pk) {
    console.error("CRITICAL: NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is missing!");
  }

  return (
    <ClerkProvider 
      publishableKey={pk}
      afterSignOutUrl="/"
    >
      <html lang="en" className="dark">
        <body className="bg-[#080808] text-white antialiased selection:bg-cyan-500/30">{children}</body>
      </html>
    </ClerkProvider>
  );
}
