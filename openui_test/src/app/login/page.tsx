"use client";

import { Suspense } from "react";

import { AuthScreen } from "@/components/auth-screen";

export default function LoginPage() {
  return (
    <Suspense>
      <AuthScreen initialMode="signin" />
    </Suspense>
  );
}
