"use client";

import { ArrowRight, Check, Eye, EyeOff, Moon, Sun } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { useSystemThemeMode } from "@openuidev/react-ui";

import { Backdrop } from "@/components/backdrop";
import { errorMessage } from "@/lib/api";
import { useLocalStorage } from "@/lib/use-browser";

export type AuthMode = "signin" | "signup";

const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{2,31}$/;

const BACKEND_DOWN =
  "The FastAPI backend isn't running. Start it with start.ps1 (or: uvicorn backend.main:app --reload) and refresh.";
const MONGO_DOWN =
  "MongoDB isn't running, so sign-in can't work yet. Run scripts\\start-mongodb.ps1, then refresh this page.";

/* Sample answer shown on the showcase panel. Same hues as the chart palette. */
const SAMPLE_BARS = [
  { label: "United States", value: 412, color: "var(--qc-series-1)" },
  { label: "India", value: 318, color: "var(--qc-series-2)" },
  { label: "Germany", value: 241, color: "var(--qc-series-3)" },
  { label: "United Kingdom", value: 197, color: "var(--qc-series-4)" },
  { label: "Brazil", value: 154, color: "var(--qc-series-5)" },
];

function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  hint?: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="auth-field">
      <label className="auth-label" htmlFor={id}>{label}</label>
      <div className="auth-password">
        <input
          id={id}
          className="auth-input"
          type={visible ? "text" : "password"}
          autoComplete={autoComplete}
          required
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-describedby={hint ? `${id}-hint` : undefined}
        />
        <button
          type="button"
          className="auth-reveal"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? "Hide password" : "Show password"}
        >
          {visible ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </div>
      {hint && <p id={`${id}-hint`} className="auth-hint">{hint}</p>}
    </div>
  );
}

function Showcase() {
  const max = Math.max(...SAMPLE_BARS.map((bar) => bar.value));
  return (
    <aside className="auth-showcase" aria-hidden="true">
      <div className="auth-showcase__inner">
        <p className="auth-showcase__eyebrow">Queryable Chatbot · Data intelligence</p>
        <h2 className="auth-showcase__headline">
          Ask your data anything.
          <br />
          <em>See the answer.</em>
        </h2>

        <div className="auth-demo">
          <div className="auth-demo__question">Top 5 countries by annual HR tech spend</div>
          <div className="auth-demo__card">
            <div className="auth-demo__head">
              <span>Annual HR tech spend</span>
              <span className="auth-demo__unit">USD, millions</span>
            </div>
            <ul className="auth-demo__bars">
              {SAMPLE_BARS.map((bar, index) => (
                <li key={bar.label} style={{ ["--i" as string]: index }}>
                  <span className="auth-demo__label">{bar.label}</span>
                  <span className="auth-demo__track">
                    <span
                      className="auth-demo__bar"
                      style={{ width: `${(bar.value / max) * 100}%`, background: bar.color }}
                    />
                  </span>
                  <span className="auth-demo__value">{bar.value}</span>
                </li>
              ))}
            </ul>
            <div className="auth-demo__foot">
              <Check size={13} /> Verified against 5 rows from <code>span_companies</code>
            </div>
          </div>
        </div>

        <ul className="auth-points">
          <li>Plain-language questions, no query syntax</li>
          <li>Charts, tables and metrics rendered live</li>
          <li>Every figure grounded in your MongoDB data</li>
        </ul>
      </div>
    </aside>
  );
}

export function AuthScreen({ initialMode }: { initialMode: AuthMode }) {
  const params = useSearchParams();
  const ids = useId();
  const systemMode = useSystemThemeMode();
  const [savedTheme, setSavedTheme] = useLocalStorage("queryable-chat-theme");
  const theme = savedTheme === "dark" || savedTheme === "light" ? savedTheme : systemMode;

  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [signupEnabled, setSignupEnabled] = useState(true);
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [serviceIssue, setServiceIssue] = useState("");

  const expired = params.get("expired") === "1";
  const isSignup = mode === "signup" && signupEnabled;

  useEffect(() => {
    fetch("/api/auth/config")
      .then((response) => (response.ok ? response.json() : null))
      .then((config: { signup_enabled?: boolean } | null) => {
        if (config && config.signup_enabled === false) {
          setSignupEnabled(false);
          setMode("signin");
        }
      })
      .catch(() => {});

    // Say up front which service is down instead of failing on submit.
    fetch("/api/health")
      .then(async (response) => {
        if (!response.ok) throw new Error();
        const health = (await response.json()) as { mongodb?: string };
        setServiceIssue(health.mongodb === "ok" ? "" : MONGO_DOWN);
      })
      .catch(() => setServiceIssue(BACKEND_DOWN));
  }, []);

  const switchMode = (next: AuthMode) => {
    setMode(next);
    setError("");
    setPassword("");
    setConfirm("");
    window.history.replaceState(null, "", next === "signup" ? "/signup" : "/login");
  };

  const validate = (): string => {
    if (!isSignup) return "";
    const normalized = username.trim().toLowerCase();
    if (!USERNAME_RE.test(normalized)) {
      return "Usernames are 3–32 characters: letters, numbers, dots, dashes or underscores.";
    }
    if (password.length < 8) return "Use at least 8 characters for your password.";
    if (password !== confirm) return "The two passwords don't match.";
    return "";
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      const response = await fetch(isSignup ? "/api/auth/signup" : "/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(
          isSignup
            ? { username: username.trim(), password, display_name: name.trim() }
            : { username, password },
        ),
      });
      if (!response.ok) {
        // 503 carries the backend's own explanation (e.g. MongoDB down); any
        // other 5xx without one means the Next.js proxy couldn't reach FastAPI.
        setError(
          await errorMessage(
            response,
            response.status >= 500 ? BACKEND_DOWN : isSignup ? "Could not create your account." : "Sign-in failed.",
          ),
        );
        if (response.status === 503) setServiceIssue("");
        return;
      }
      window.location.assign("/");
    } catch {
      setError(BACKEND_DOWN);
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit = isSignup
    ? Boolean(username && password && confirm)
    : Boolean(username && password);

  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <main className="qc-app auth" data-theme={theme}>
      <Backdrop />
      <section className="auth-panel">
        <header className="auth-topbar">
          <a className="auth-brand" href="/login">
            <img src={theme === "dark" ? "/queryable-logo-dark.svg" : "/queryable-logo-light.svg"} alt="" width={30} height={30} />
            <span>Queryable <span className="auth-brand__accent">Chatbot</span></span>
          </a>
          <button
            type="button"
            className="qc-icon-button"
            onClick={() => setSavedTheme(nextTheme)}
            aria-label={`Switch to ${nextTheme} mode`}
            title={`Switch to ${nextTheme} mode`}
          >
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </header>

        <div className="auth-body">
          <h1 className="auth-title">{isSignup ? "Create your account" : "Welcome back"}</h1>
          <p className="auth-subtitle">
            {isSignup
              ? "Start asking questions about your business data in seconds."
              : "Sign in to continue to Queryable Chatbot."}
          </p>

          {signupEnabled && (
            <div className="auth-tabs" role="tablist" aria-label="Account">
              <button
                type="button"
                role="tab"
                aria-selected={!isSignup}
                className="auth-tab"
                onClick={() => switchMode("signin")}
              >
                Sign in
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={isSignup}
                className="auth-tab"
                onClick={() => switchMode("signup")}
              >
                Sign up
              </button>
            </div>
          )}

          {serviceIssue && !error && (
            <p className="auth-notice auth-notice--warning" role="status">{serviceIssue}</p>
          )}

          {expired && !error && !serviceIssue && !isSignup && (
            <p className="auth-notice" role="status">Your session ended. Please sign in again.</p>
          )}

          <form className="auth-form" onSubmit={submit} noValidate>
            {isSignup && (
              <div className="auth-field">
                <label className="auth-label" htmlFor={`${ids}-name`}>
                  Full name <span className="auth-optional">optional</span>
                </label>
                <input
                  id={`${ids}-name`}
                  className="auth-input"
                  autoComplete="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
            )}

            <div className="auth-field">
              <label className="auth-label" htmlFor={`${ids}-username`}>Username</label>
              <input
                id={`${ids}-username`}
                className="auth-input"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                autoFocus
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </div>

            <PasswordField
              id={`${ids}-password`}
              label="Password"
              value={password}
              onChange={setPassword}
              autoComplete={isSignup ? "new-password" : "current-password"}
              hint={isSignup ? "At least 8 characters." : undefined}
            />

            {isSignup && (
              <PasswordField
                id={`${ids}-confirm`}
                label="Confirm password"
                value={confirm}
                onChange={setConfirm}
                autoComplete="new-password"
              />
            )}

            <p className="auth-error" role="alert" aria-live="assertive">{error}</p>

            <button className="auth-submit" type="submit" disabled={submitting || !canSubmit}>
              {submitting
                ? isSignup ? "Creating account…" : "Signing in…"
                : isSignup ? "Create account" : "Continue"}
              {!submitting && <ArrowRight size={17} />}
            </button>
          </form>

          <p className="auth-switch">
            {!signupEnabled
              ? "Need access? Ask your administrator for an account."
              : isSignup
                ? <>Already have an account? <button type="button" onClick={() => switchMode("signin")}>Sign in</button></>
                : <>Don&apos;t have an account? <button type="button" onClick={() => switchMode("signup")}>Sign up</button></>}
          </p>
        </div>

        <footer className="auth-footer">Your session is private to you and expires after inactivity.</footer>
      </section>

      <Showcase />
    </main>
  );
}
