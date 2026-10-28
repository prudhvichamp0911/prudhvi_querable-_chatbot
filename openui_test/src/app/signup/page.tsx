"use client";

import { Suspense } from "react";

import { AuthScreen } from "@/components/auth-screen";

export default function SignupPage() {
  return (
    <Suspense>
      <AuthScreen initialMode="signup" />
    </Suspense>
  );
}
