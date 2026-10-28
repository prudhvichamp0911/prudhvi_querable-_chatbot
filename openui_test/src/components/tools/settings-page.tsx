"use client";

import { useState, type FormEvent } from "react";
import {
  BarChart3,
  Check,
  Copy,
  CreditCard,
  KeyRound,
  LogOut,
  Monitor,
  Moon,
  Plus,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
  UserRound,
} from "lucide-react";

import { LoadState, ToolPage, useApi } from "@/components/tools/shared";
import { authFetch, errorMessage, logout, type SessionUser } from "@/lib/api";
import { formatValue } from "@/lib/geo";

type Plan = {
  id: string;
  name: string;
  price_usd: number;
  period: string;
  tagline: string;
  messages_per_day: number | null;
  api_keys: number;
  features: string[];
};

type Overview = {
  profile: { username: string; display_name: string; role: string; created_at: string | null };
  plan: string;
  plans: Plan[];
  billing_simulated: boolean;
  limits_enforced: boolean;
  usage: {
    today: number;
    limit: number | null;
    days: { day: string; messages: number; tokens: number; cost_usd: number }[];
    total_messages: number;
    total_tokens: number;
    total_cost_usd: number;
  };
  api_keys: { count: number; limit: number };
};

type ApiKey = { id: string; name: string; preview: string; created_at: string | null; last_used_at: string | null };

type ThemeChoice = "light" | "dark" | "system";

const TABS = [
  { id: "general", label: "General", icon: <Settings2 size={15} /> },
  { id: "account", label: "Account", icon: <UserRound size={15} /> },
  { id: "billing", label: "Plan & billing", icon: <CreditCard size={15} /> },
  { id: "keys", label: "API keys", icon: <KeyRound size={15} /> },
  { id: "usage", label: "Usage", icon: <BarChart3 size={15} /> },
] as const;

type TabId = (typeof TABS)[number]["id"];

async function send(url: string, method: string, body?: unknown) {
  const response = await authFetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Something went wrong. Please try again."));
  return response.json();
}

const dateText = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—";

function Row({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="qc-set-row">
      <div className="qc-set-row__text">
        <strong>{title}</strong>
        {hint && <span>{hint}</span>}
      </div>
      <div className="qc-set-row__control">{children}</div>
    </div>
  );
}

function Status({ error, ok }: { error: string; ok: string }) {
  if (error) return <p className="qc-set-status qc-set-status--error" role="alert">{error}</p>;
  if (ok) return <p className="qc-set-status" role="status"><Check size={13} /> {ok}</p>;
  return null;
}

// ------------------------------------------------------------------ General

function GeneralTab({
  theme,
  onTheme,
  models,
  model,
  onModel,
}: {
  theme: ThemeChoice;
  onTheme: (choice: ThemeChoice) => void;
  models: { id: string; name: string; group: string }[];
  model: string;
  onModel: (id: string) => void;
}) {
  const choices: { id: ThemeChoice; label: string; icon: React.ReactNode }[] = [
    { id: "light", label: "Light", icon: <Sun size={14} /> },
    { id: "dark", label: "Dark", icon: <Moon size={14} /> },
    { id: "system", label: "System", icon: <Monitor size={14} /> },
  ];
  return (
    <section className="qc-set-card">
      <Row title="Appearance" hint="Applies to this browser.">
        <div className="qc-segmented" role="radiogroup" aria-label="Appearance">
          {choices.map((choice) => (
            <button
              key={choice.id}
              type="button"
              role="radio"
              aria-checked={theme === choice.id}
              className={theme === choice.id ? "is-active" : ""}
              onClick={() => onTheme(choice.id)}
            >
              {choice.icon} {choice.label}
            </button>
          ))}
        </div>
      </Row>
      <Row title="Default model" hint="Used for new answers. You can still switch per conversation.">
        <select className="qc-select" value={model} onChange={(event) => onModel(event.target.value)} disabled={!models.length}>
          {models.map((option) => (
            <option key={option.id} value={option.id}>
              {option.group} · {option.name}
            </option>
          ))}
        </select>
      </Row>
      <Row title="Data access" hint="Answers are read-only queries against your MongoDB. Personal data is masked.">
        <span className="qc-pill"><ShieldCheck size={12} />&nbsp;Read-only</span>
      </Row>
    </section>
  );
}

// ------------------------------------------------------------------ Account

function AccountTab({ data, onRenamed }: { data: Overview; onRenamed: (name: string) => void }) {
  const [name, setName] = useState(data.profile.display_name);
  const [nameState, setNameState] = useState({ error: "", ok: "" });
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [pwState, setPwState] = useState({ error: "", ok: "" });
  const [sessionsState, setSessionsState] = useState({ error: "", ok: "" });
  const [busy, setBusy] = useState("");

  const saveName = async (event: FormEvent) => {
    event.preventDefault();
    setBusy("name");
    try {
      const body = await send("/api/account/profile", "PATCH", { display_name: name });
      onRenamed(body.display_name);
      setNameState({ error: "", ok: "Name saved." });
    } catch (err) {
      setNameState({ error: (err as Error).message, ok: "" });
    } finally {
      setBusy("");
    }
  };

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (next.length < 8) {
      setPwState({ error: "Use at least 8 characters for the new password.", ok: "" });
      return;
    }
    setBusy("password");
    try {
      await send("/api/account/password", "POST", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setPwState({ error: "", ok: "Password changed. Other devices were signed out." });
    } catch (err) {
      setPwState({ error: (err as Error).message, ok: "" });
    } finally {
      setBusy("");
    }
  };

  const revokeOthers = async () => {
    setBusy("sessions");
    try {
      const body = await send("/api/account/sessions/revoke", "POST");
      setSessionsState({ error: "", ok: `Signed out of ${body.revoked} other session${body.revoked === 1 ? "" : "s"}.` });
    } catch (err) {
      setSessionsState({ error: (err as Error).message, ok: "" });
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <section className="qc-set-card">
        <div className="qc-set-profile">
          <span className="qc-set-profile__avatar" aria-hidden="true">{data.profile.display_name.slice(0, 1).toUpperCase()}</span>
          <div>
            <strong>{data.profile.display_name}</strong>
            <span>
              @{data.profile.username} · {data.profile.role === "admin" ? "Administrator" : "Analyst"} · member since{" "}
              {dateText(data.profile.created_at)}
            </span>
          </div>
        </div>
        <form className="qc-set-form" onSubmit={saveName}>
          <label htmlFor="qc-set-name">Display name</label>
          <div className="qc-set-inline">
            <input id="qc-set-name" className="qc-input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
            <button className="qc-primary-button" type="submit" disabled={busy === "name" || !name.trim() || name === data.profile.display_name}>
              Save
            </button>
          </div>
          <Status {...nameState} />
        </form>
      </section>

      <section className="qc-set-card">
        <h3 className="qc-set-card__title">Password</h3>
        <form className="qc-set-form" onSubmit={changePassword}>
          <label htmlFor="qc-set-current">Current password</label>
          <input
            id="qc-set-current"
            className="qc-input"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
          <label htmlFor="qc-set-new">New password</label>
          <input
            id="qc-set-new"
            className="qc-input"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
          <div>
            <button className="qc-primary-button" type="submit" disabled={busy === "password" || !current || !next}>
              Change password
            </button>
          </div>
          <Status {...pwState} />
        </form>
      </section>

      <section className="qc-set-card">
        <Row title="Other devices" hint="Sign out everywhere except this browser.">
          <button className="qc-ghost-button" type="button" onClick={revokeOthers} disabled={busy === "sessions"}>
            Sign out other sessions
          </button>
        </Row>
        <Status {...sessionsState} />
        <Row title="This device" hint="End your session in this browser.">
          <button className="qc-ghost-button qc-ghost-button--danger" type="button" onClick={() => void logout()}>
            <LogOut size={13} /> Sign out
          </button>
        </Row>
      </section>
    </>
  );
}

// ------------------------------------------------------------------ Billing

function UsageMeter({ used, limit }: { used: number; limit: number | null }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  return (
    <div className="qc-meter">
      <div className="qc-meter__head">
        <span>Questions today</span>
        <strong>{limit == null ? `${used} · unlimited` : `${used} / ${limit}`}</strong>
      </div>
      <span className="qc-meter__track">
        <span className={`qc-meter__bar ${pct >= 90 ? "is-high" : ""}`} style={{ width: `${limit == null ? 6 : pct}%` }} />
      </span>
    </div>
  );
}

function BillingTab({ data, onChanged }: { data: Overview; onChanged: (plan: string) => void }) {
  const [busy, setBusy] = useState("");
  const [state, setState] = useState({ error: "", ok: "" });
  const order = data.plans.map((plan) => plan.id);

  const choose = async (plan: Plan) => {
    setBusy(plan.id);
    try {
      await send("/api/account/plan", "POST", { plan: plan.id });
      setState({ error: "", ok: `You're now on ${plan.name}.` });
      onChanged(plan.id);
    } catch (err) {
      setState({ error: (err as Error).message, ok: "" });
    } finally {
      setBusy("");
    }
  };

  return (
    <>
      <section className="qc-set-card">
        <UsageMeter used={data.usage.today} limit={data.limits_enforced ? data.usage.limit : null} />
        {data.billing_simulated && (
          <p className="qc-set-note">
            <Sparkles size={13} /> Demo billing: no payment processor is connected, so plan changes apply instantly
            and nothing is charged.
          </p>
        )}
        <Status {...state} />
      </section>

      <div className="qc-plans">
        {data.plans.map((plan) => {
          const current = plan.id === data.plan;
          const upgrade = order.indexOf(plan.id) > order.indexOf(data.plan);
          return (
            <article key={plan.id} className={`qc-plan ${current ? "is-current" : ""} ${plan.id === "pro" ? "is-featured" : ""}`}>
              <header>
                <h3>{plan.name}</h3>
                {current ? <span className="qc-pill">Current plan</span> : plan.id === "pro" && <span className="qc-pill">Popular</span>}
              </header>
              <p className="qc-plan__tagline">{plan.tagline}</p>
              <p className="qc-plan__price">
                <strong>${plan.price_usd}</strong> <span>{plan.period}</span>
              </p>
              <ul>
                {plan.features.map((feature) => (
                  <li key={feature}>
                    <Check size={14} /> {feature}
                  </li>
                ))}
              </ul>
              <button
                type="button"
                className={current ? "qc-ghost-button" : upgrade ? "qc-primary-button" : "qc-ghost-button"}
                disabled={current || busy !== ""}
                onClick={() => choose(plan)}
              >
                {current ? "Your plan" : busy === plan.id ? "Switching…" : upgrade ? `Upgrade to ${plan.name}` : `Switch to ${plan.name}`}
              </button>
            </article>
          );
        })}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ API keys

function KeysTab({ data, onChanged }: { data: Overview; onChanged: () => void }) {
  const keys = useApi<{ keys: ApiKey[] }>("/api/account/keys");
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState("");
  const [copied, setCopied] = useState("");
  const [state, setState] = useState({ error: "", ok: "" });

  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const curl = `curl ${origin}/api/models \\\n  -H "Authorization: Bearer ${secret || "$QUERYABLE_API_KEY"}"`;

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
      window.setTimeout(() => setCopied(""), 1600);
    } catch {
      setState({ error: "Copy failed. Select the text and copy it manually.", ok: "" });
    }
  };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setCreating(true);
    try {
      const body = await send("/api/account/keys", "POST", { name });
      setSecret(body.key);
      setName("");
      setState({ error: "", ok: "" });
      keys.reload();
      onChanged();
    } catch (err) {
      setState({ error: (err as Error).message, ok: "" });
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (key: ApiKey) => {
    if (!window.confirm(`Revoke "${key.name}"? Apps using it will stop working immediately.`)) return;
    try {
      await send(`/api/account/keys/${encodeURIComponent(key.id)}`, "DELETE");
      setState({ error: "", ok: `"${key.name}" revoked.` });
      keys.reload();
      onChanged();
    } catch (err) {
      setState({ error: (err as Error).message, ok: "" });
    }
  };

  return (
    <>
      <section className="qc-set-card">
        <p className="qc-set-lede">
          Use a secret key to call the Queryable API from scripts and notebooks. Keys act as you, can read your
          data and count toward your plan, but cannot change your account. Keep them out of shared code.
        </p>
        <form className="qc-set-inline" onSubmit={create}>
          <input
            className="qc-input"
            placeholder="Key name, e.g. Weekly report"
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
            aria-label="Key name"
          />
          <button className="qc-primary-button" type="submit" disabled={creating || data.api_keys.count >= data.api_keys.limit}>
            <Plus size={14} /> Create secret key
          </button>
        </form>
        <p className="qc-muted qc-set-small">
          {data.api_keys.count} of {data.api_keys.limit} keys used on your plan.
        </p>
        <Status {...state} />

        {secret && (
          <div className="qc-secret" role="status">
            <strong>Save your key now</strong>
            <span>For your security it won&apos;t be shown again. If you lose it, create a new one.</span>
            <div className="qc-secret__value">
              <code>{secret}</code>
              <button type="button" className="qc-ghost-button" onClick={() => copy(secret, "secret")}>
                {copied === "secret" ? <Check size={13} /> : <Copy size={13} />} {copied === "secret" ? "Copied" : "Copy"}
              </button>
            </div>
            <button type="button" className="qc-link-button" onClick={() => setSecret("")}>
              I&apos;ve saved it
            </button>
          </div>
        )}
      </section>

      <section className="qc-set-card qc-set-card--flush">
        <LoadState loading={keys.loading && !keys.data} error={keys.error} onRetry={keys.reload} />
        {keys.data && keys.data.keys.length === 0 && <p className="qc-muted qc-set-empty">No keys yet.</p>}
        {keys.data && keys.data.keys.length > 0 && (
          <div className="qc-table-wrap">
            <table className="qc-keys">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Secret key</th>
                  <th>Created</th>
                  <th>Last used</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {keys.data.keys.map((key) => (
                  <tr key={key.id}>
                    <td>{key.name}</td>
                    <td><code>{key.preview}</code></td>
                    <td>{dateText(key.created_at)}</td>
                    <td>{key.last_used_at ? dateText(key.last_used_at) : "Never"}</td>
                    <td>
                      <button type="button" className="qc-icon-button" aria-label={`Revoke ${key.name}`} title="Revoke" onClick={() => revoke(key)}>
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="qc-set-card">
        <div className="qc-set-card__head">
          <h3 className="qc-set-card__title">Quickstart</h3>
          <button type="button" className="qc-ghost-button" onClick={() => copy(curl, "curl")}>
            {copied === "curl" ? <Check size={13} /> : <Copy size={13} />} {copied === "curl" ? "Copied" : "Copy"}
          </button>
        </div>
        <pre className="qc-code"><code>{curl}</code></pre>
        <p className="qc-muted qc-set-small">
          Every <code>/api/*</code> endpoint accepts the key, for example <code>POST /ask</code> on the backend
          (port 8000) with <code>{'{"question": "..."}'}</code>.
        </p>
      </section>
    </>
  );
}

// ------------------------------------------------------------------ Usage

function UsageTab({ data }: { data: Overview }) {
  const max = Math.max(1, ...data.usage.days.map((day) => day.messages));
  const tiles = [
    { label: "Questions", value: formatValue(data.usage.total_messages), hint: "last 14 days" },
    { label: "Tokens", value: formatValue(data.usage.total_tokens), hint: "prompt + completion" },
    { label: "Model cost", value: `$${data.usage.total_cost_usd.toFixed(4)}`, hint: "OpenRouter spend" },
    { label: "Today", value: formatValue(data.usage.today), hint: data.usage.limit ? `of ${data.usage.limit} allowed` : "no daily limit" },
  ];
  return (
    <>
      <section className="qc-kpi-row">
        {tiles.map((tile) => (
          <article key={tile.label} className="qc-kpi">
            <span className="qc-kpi__label">{tile.label}</span>
            <span className="qc-kpi__value">{tile.value}</span>
            <span className="qc-kpi__hint">{tile.hint}</span>
          </article>
        ))}
      </section>
      <section className="qc-set-card">
        <h3 className="qc-set-card__title">Questions per day</h3>
        <div className="qc-usage-chart" role="img" aria-label={`Questions per day over the last 14 days, ${data.usage.total_messages} in total`}>
          {data.usage.days.map((day, index) => (
            <div key={day.day} className="qc-usage-chart__col" title={`${day.day}: ${day.messages} questions`}>
              <span className="qc-usage-chart__value">{day.messages || ""}</span>
              <span
                className="qc-usage-chart__bar"
                style={{ height: `${Math.max(2, (day.messages / max) * 100)}%`, ["--i" as string]: index }}
              />
              <span className="qc-usage-chart__day">
                {new Date(`${day.day}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" })}
              </span>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

// ------------------------------------------------------------------ Page

export function SettingsPage({
  theme,
  onTheme,
  models,
  model,
  onModel,
  onUserChange,
}: {
  theme: ThemeChoice;
  onTheme: (choice: ThemeChoice) => void;
  models: { id: string; name: string; group: string }[];
  model: string;
  onModel: (id: string) => void;
  onUserChange: (patch: Partial<SessionUser>) => void;
}) {
  const [tab, setTab] = useState<TabId>("general");
  const { data, error, loading, reload } = useApi<Overview>("/api/account/overview");

  return (
    <ToolPage icon={<Settings2 size={13} />} eyebrow="Settings" title="Settings" description="Your preferences, account, plan and API access.">
      <div className="qc-settings">
        <nav className="qc-settings__tabs" aria-label="Settings sections" role="tablist">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={tab === item.id}
              className={tab === item.id ? "is-active" : ""}
              onClick={() => setTab(item.id)}
            >
              {item.icon} {item.label}
            </button>
          ))}
        </nav>

        <div className="qc-settings__panel" role="tabpanel">
          {tab === "general" ? (
            <GeneralTab theme={theme} onTheme={onTheme} models={models} model={model} onModel={onModel} />
          ) : (
            <>
              <LoadState loading={loading && !data} error={error} onRetry={reload} />
              {data && tab === "account" && (
                <AccountTab data={data} onRenamed={(display_name) => { onUserChange({ display_name }); reload(); }} />
              )}
              {data && tab === "billing" && (
                <BillingTab data={data} onChanged={(plan) => { onUserChange({ plan }); reload(); }} />
              )}
              {data && tab === "keys" && <KeysTab data={data} onChanged={reload} />}
              {data && tab === "usage" && <UsageTab data={data} />}
            </>
          )}
        </div>
      </div>
    </ToolPage>
  );
}
