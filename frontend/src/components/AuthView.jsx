import { useState } from "react";
import Logo from "./Logo";

// Combined login / signup card. `mode` is "login" | "signup"; the parent owns
// the actual auth calls (so localStorage + app state stay in one place).
export default function AuthView({
  mode = "login",
  onLogin,
  onSignup,
  onSwitch,
  onClose,
  gated = false,
  onViewPricing,
}) {
  const isSignup = mode === "signup";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    if (isSignup && password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      if (isSignup) {
        await onSignup({ email: email.trim(), password, name: name.trim() });
      } else {
        await onLogin({ email: email.trim(), password });
      }
      onClose?.();
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center px-5 py-16">
      <div className="mb-8 flex items-center gap-2.5">
        <Logo size={32} />
        <span className="text-lg font-bold tracking-tight text-white">Deepfield</span>
      </div>

      <div className="w-full rounded-2xl border border-white/10 bg-white/[0.03] p-7 shadow-xl backdrop-blur-xl">
        <h1 className="text-center text-2xl font-extrabold tracking-tight text-white">
          {isSignup ? "Create your account" : "Welcome back"}
        </h1>
        <p className="mt-1.5 mb-6 text-center text-[13.5px] text-white/50">
          {gated
            ? "Create a free account to start researching — 3 deep runs a month, on the house."
            : isSignup
            ? "Save your research and unlock the disagreement graph."
            : "Sign in to pick up where you left off."}
        </p>

        <form onSubmit={submit} className="space-y-3.5">
          {isSignup && (
            <Field
              label="Name"
              type="text"
              value={name}
              onChange={setName}
              placeholder="Ada Lovelace"
              autoComplete="name"
            />
          )}
          <Field
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            placeholder="you@lab.org"
            autoComplete="email"
            required
          />
          <Field
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder={isSignup ? "At least 8 characters" : "••••••••"}
            autoComplete={isSignup ? "new-password" : "current-password"}
            required
          />

          {error && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[13px] text-rose-200">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-xl bg-gradient-to-r from-accent to-accent-cyan px-4 py-2.5 text-sm font-semibold text-white shadow-glow transition hover:brightness-110 disabled:opacity-60"
          >
            {busy ? "Please wait…" : isSignup ? "Create account" : "Sign in"}
          </button>
        </form>

        <p className="mt-5 text-center text-[13px] text-white/50">
          {isSignup ? "Already have an account?" : "New to Deepfield?"}{" "}
          <button
            onClick={() => onSwitch?.(isSignup ? "login" : "signup")}
            className="font-medium text-accent-cyan hover:underline"
          >
            {isSignup ? "Sign in" : "Create one"}
          </button>
        </p>
      </div>

      {gated ? (
        <button
          onClick={() => onViewPricing?.()}
          className="mt-6 text-[13px] text-white/40 transition hover:text-white/70"
        >
          See pricing & plans →
        </button>
      ) : (
        <button
          onClick={() => (window.location.hash = "")}
          className="mt-6 text-[13px] text-white/40 transition hover:text-white/70"
        >
          ← Back to research
        </button>
      )}
    </div>
  );
}

function Field({ label, type, value, onChange, placeholder, autoComplete, required }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12.5px] font-medium text-white/60">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        required={required}
        className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-accent-glow/60 focus:outline-none focus:ring-1 focus:ring-accent-glow/30"
      />
    </label>
  );
}
