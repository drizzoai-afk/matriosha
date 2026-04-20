import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[--bg-base] px-4">
      <SignIn forceRedirectUrl="/dashboard" />
    </main>
  );
}
