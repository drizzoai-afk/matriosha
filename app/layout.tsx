import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata = {
  title: "Matriosha — Secure Agentic Memory",
  description: "Your sovereign digital brain.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider 
      proxyUrl="https://matriosha.in/__clerk/"
      afterSignInUrl="/dashboard"
      afterSignUpUrl="/dashboard"
      afterSignOutUrl="/"
      signInUrl="/sign-in"
      signUpUrl="/sign-up"
    >
      <html lang="en" className="dark">
        <body className="bg-[#080808] text-white antialiased selection:bg-cyan-500/30">{children}</body>
      </html>
    </ClerkProvider>
  );
}
