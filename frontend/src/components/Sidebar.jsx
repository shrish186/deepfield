import { useState } from "react";
import Logo from "./Logo";

function NavItem({ icon, label, onClick, primary }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-3 w-full rounded-xl px-3 py-2 text-sm transition-colors ${
        primary
          ? "bg-gradient-to-r from-accent/90 to-accent-cyan/80 text-white font-medium shadow-glow hover:brightness-110"
          : "text-white/70 hover:text-white hover:bg-white/5"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

export default function Sidebar({
  onNewResearch,
  threads = [],
  activeThreadId,
  onSelectThread,
  onOpenGraph,
  graphActive,
  user,
  usage,
  onLogin,
  onSignup,
  onLogout,
  onOpenPricing,
}) {
  const [historyQuery, setHistoryQuery] = useState("");
  const q = historyQuery.trim().toLowerCase();
  const filtered = q
    ? threads.filter((t) => (t.title || "").toLowerCase().includes(q))
    : threads;
  return (
    <aside className="hidden md:flex w-[264px] shrink-0 flex-col gap-5 border-r border-white/8 bg-ink-900/60 backdrop-blur-xl px-4 py-5">
      <div className="flex items-center gap-2.5 px-1">
        <Logo size={26} />
        <span className="text-[15px] font-bold tracking-tight text-white">
          Deepfield
        </span>
      </div>

      <div className="flex flex-col gap-1">
        <NavItem
          primary
          onClick={onNewResearch}
          label="New research"
          icon={
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          }
        />
        <button
          onClick={onOpenGraph}
          className={`flex items-center gap-3 w-full rounded-xl px-3 py-2 text-sm transition-colors ${
            graphActive
              ? "bg-white/8 text-white"
              : "text-white/70 hover:text-white hover:bg-white/5"
          }`}
        >
          <span className="text-[15px] leading-none">🧠</span>
          Disagreement graph
        </button>
      </div>

      <div className="h-px bg-white/8" />

      <div className="flex min-h-0 flex-1 flex-col">
        <h3 className="px-1 pb-2 text-[11px] font-semibold uppercase tracking-wider text-white/40">
          History
        </h3>
        {threads.length > 0 && (
          <input
            value={historyQuery}
            onChange={(e) => setHistoryQuery(e.target.value)}
            placeholder="Search history…"
            className="mb-2 w-full rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-1.5 text-[12px] text-white/85 placeholder:text-white/30 focus:border-accent-glow/50 focus:outline-none"
          />
        )}
        {threads.length === 0 ? (
          <p className="px-1 text-[12.5px] leading-relaxed text-white/40">
            Your saved research threads will appear here.
          </p>
        ) : filtered.length === 0 ? (
          <p className="px-1 text-[12.5px] leading-relaxed text-white/40">
            No threads match “{historyQuery.trim()}”.
          </p>
        ) : (
          <div className="-mx-1 space-y-0.5 overflow-y-auto pr-0.5">
            {filtered.map((t) => (
              <button
                key={t.id}
                onClick={() => onSelectThread?.(t.id)}
                className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[13px] transition-colors ${
                  t.id === activeThreadId
                    ? "bg-white/8 text-white"
                    : "text-white/60 hover:bg-white/5 hover:text-white/90"
                }`}
              >
                <svg className="shrink-0 opacity-50" width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                </svg>
                <span className="truncate">{t.title}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-auto space-y-3 px-1">
        <div className="h-px bg-white/8" />

        <button
          onClick={onOpenPricing}
          className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-sm text-white/70 transition-colors hover:bg-white/5 hover:text-white"
        >
          <span className="text-[15px] leading-none">✨</span>
          Pricing & plans
        </button>

        {user ? (
          <div className="rounded-xl border border-white/8 bg-white/[0.03] p-2.5">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-cyan text-[13px] font-bold text-white">
                {(user.name || user.email || "?").trim().charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium text-white">
                  {user.name || user.email}
                </div>
                <div className="truncate text-[11px] capitalize text-white/45">
                  {user.plan || "free"} plan
                </div>
              </div>
            </div>

            {usage && (
              usage.limit == null ? (
                <div className="mt-2 rounded-lg bg-white/[0.04] px-2 py-1.5 text-[11.5px] text-white/55">
                  ✦ Unlimited deep runs
                </div>
              ) : (
                <div className="mt-2 rounded-lg bg-white/[0.04] px-2 py-1.5">
                  <div className="flex items-center justify-between text-[11.5px]">
                    <span className="text-white/55">Deep runs this month</span>
                    <span
                      className={
                        usage.remaining === 0
                          ? "font-semibold text-amber-300"
                          : "font-semibold text-white/80"
                      }
                    >
                      {usage.remaining}/{usage.limit} left
                    </span>
                  </div>
                  <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-accent to-accent-cyan"
                      style={{
                        width: `${Math.max(0, Math.min(100, (usage.remaining / usage.limit) * 100))}%`,
                      }}
                    />
                  </div>
                  {usage.remaining === 0 && (
                    <button
                      onClick={onOpenPricing}
                      className="mt-2 w-full rounded-md bg-gradient-to-r from-accent to-accent-cyan px-2 py-1 text-[11.5px] font-semibold text-white"
                    >
                      Upgrade for unlimited →
                    </button>
                  )}
                </div>
              )
            )}

            <button
              onClick={onLogout}
              className="mt-2 w-full rounded-lg border border-white/10 px-2 py-1.5 text-[12px] text-white/60 transition hover:bg-white/5 hover:text-white"
            >
              Sign out
            </button>
          </div>
        ) : (
          <div className="space-y-1.5">
            <button
              onClick={onSignup}
              className="w-full rounded-xl bg-gradient-to-r from-accent/90 to-accent-cyan/80 px-3 py-2 text-[13px] font-medium text-white shadow-glow transition hover:brightness-110"
            >
              Create account
            </button>
            <button
              onClick={onLogin}
              className="w-full rounded-xl px-3 py-2 text-[13px] text-white/70 transition hover:bg-white/5 hover:text-white"
            >
              Sign in
            </button>
          </div>
        )}

        <div className="flex items-center gap-2 text-[11px] text-white/40">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
          Powered by Claude + Tavily
        </div>
      </div>
    </aside>
  );
}
