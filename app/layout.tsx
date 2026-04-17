import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

export const metadata = {
  title: "Matriosha — Secure Agentic Memory",
  description: "Your sovereign digital brain.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en" className="dark">
        <body className="bg-black text-white antialiased">{children}</body>
      </html>
    </ClerkProvider>
  );
}
