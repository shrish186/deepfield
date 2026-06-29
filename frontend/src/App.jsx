import { useCallback, useEffect, useState } from "react";
import Sidebar from "./components/Sidebar";
import Logo from "./components/Logo";
import QueryInput from "./components/QueryInput";
import Turn from "./components/Turn";
import GraphExplorer from "./components/GraphExplorer";
import AuthView from "./components/AuthView";
import KeySettings from "./components/KeySettings";
import { useAuth } from "./hooks/useAuth";
import {
  createReport,
  getThread,
  getReport,
  listThreads,
  getUsage,
  getDisagreements,
  hasByok,
} from "./api";

// Deliberately contested questions — topics where credible sources genuinely
// disagree, so the conflict-surfacing pipeline has something to show off.
const EXAMPLES = [
  "Does creatine damage kidney function?",
  "Is moderate alcohol consumption actually safe?",
  "Do seed oils cause chronic inflammation?",
  "Does intermittent fasting beat plain calorie counting?",
];

// Map the URL hash to a top-level "page" for the auth flows. Research and the
// deep-link #/report/{id} handling stay exactly as before.
function pageFromHash() {
  const h = window.location.hash;
  if (h.startsWith("#/login")) return "login";
  if (h.startsWith("#/signup")) return "signup";
  return null;
}

export default function App() {
  const auth = useAuth();
  const [page, setPage] = useState(pageFromHash);
  const [usage, setUsage] = useState(null); // { plan, used, limit, remaining }
  const [limited, setLimited] = useState(false);
  const [contested, setContested] = useState([]); // top graph disagreements for the hero
  const [showKeys, setShowKeys] = useState(false);
  const [byok, setByok] = useState(hasByok()); // user supplied their own API keys
  const [threadId, setThreadId] = useState(null);
  const [turns, setTurns] = useState([]); // [{ id, query, status }]
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [threads, setThreads] = useState([]);
  const [mode, setMode] = useState("deep"); // "chat" | "deep" | "basic"
  const [sourceScope, setSourceScope] = useState("web"); // "web" | "academic" | "pubmed" | "arxiv"
  const [view, setView] = useState("research"); // "research" | "graph"
  // Advanced search controls (deep/basic only): recency + domain allow/blocklist.
  const [filters, setFilters] = useState({
    yearMin: null,
    includeDomains: "",
    excludeDomains: "",
  });

  const started = turns.length > 0;
  const lastTurn = turns[turns.length - 1];
  const running =
    submitting ||
    (lastTurn != null &&
      lastTurn.status !== "completed" &&
      lastTurn.status !== "failed");

  const refreshThreads = useCallback(async () => {
    // History is per-account: clear it when signed out, and reload whenever the
    // signed-in user changes so one account never shows another's threads.
    if (!auth.user) {
      setThreads([]);
      return;
    }
    try {
      setThreads(await listThreads());
    } catch {
      // history is best-effort
    }
  }, [auth.user]);

  useEffect(() => {
    refreshThreads();
  }, [refreshThreads]);

  // Pull the most-contested claims from the accumulated graph to seed the hero.
  // Fail-soft: if the graph is empty or the call fails, the section just hides.
  useEffect(() => {
    let alive = true;
    getDisagreements(2)
      .then((d) => alive && setContested(Array.isArray(d) ? d.slice(0, 2) : []))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Keep the auth page in sync with the URL hash.
  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Track the signed-in user's monthly deep-run allowance.
  const refreshUsage = useCallback(async () => {
    if (!auth.user) {
      setUsage(null);
      return;
    }
    try {
      setUsage(await getUsage());
    } catch {
      // best-effort; the credit badge just hides if this fails
    }
  }, [auth.user]);

  useEffect(() => {
    refreshUsage();
  }, [refreshUsage]);

  const goto = (hash) => {
    window.location.hash = hash;
  };


  // Deep-link support: a shared link of the form #/report/{id} opens the thread
  // that report belongs to. Lets researchers paste a report URL to a teammate.
  useEffect(() => {
    const openFromHash = async () => {
      const m = window.location.hash.match(/#\/report\/(\d+)/);
      if (!m) return;
      const reportId = Number(m[1]);
      try {
        const r = await getReport(reportId);
        if (r?.id) {
          // Find which thread holds it, then open that thread's turns.
          const all = await listThreads();
          for (const th of all) {
            const detail = await getThread(th.id);
            if (detail.reports?.some((rep) => rep.id === reportId)) {
              setView("research");
              setThreadId(detail.id);
              setTurns(
                detail.reports.map((rep) => ({
                  id: rep.id,
                  query: rep.query,
                  status: rep.status,
                  mode: rep.mode || "deep",
                  source_scope: rep.source_scope || "web",
                }))
              );
              break;
            }
          }
        }
      } catch {
        /* invalid link — fall through to hero */
      }
    };
    openFromHash();
    window.addEventListener("hashchange", openFromHash);
    return () => window.removeEventListener("hashchange", openFromHash);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (q, opts = {}) => {
    const text = q.trim();
    if (!text) return;
    if (running) {
      setError("Hang on — let the current research finish before asking the next question.");
      return;
    }
    setError(null);
    setLimited(false);
    setSubmitting(true);
    const useMode = opts.mode ?? mode;
    const useScope = opts.sourceScope ?? sourceScope;
    try {
      // Search filters only apply to web/academic research modes, not Explore.
      const useFilters = useMode === "chat" ? {} : filters;
      const report = await createReport(text, {
        mode: useMode,
        sourceScope: useScope,
        threadId: opts.threadId ?? threadId,
        parentReportId: opts.parentReportId ?? null,
        context: opts.context ?? null,
        yearMin: useFilters.yearMin || null,
        includeDomains: useFilters.includeDomains?.trim() || null,
        excludeDomains: useFilters.excludeDomains?.trim() || null,
      });
      setThreadId(report.thread_id);
      setTurns((prev) => [
        ...prev,
        {
          id: report.id,
          query: text,
          status: "running",
          mode: report.mode || useMode,
          source_scope: report.source_scope || useScope,
        },
      ]);
      setQuery("");
      refreshThreads();
      // A deep run just consumed a credit — refresh the remaining count.
      if ((report.mode || useMode) === "deep") refreshUsage();
    } catch (e) {
      if (e.limited) {
        setLimited(true);
        setError(e.message);
      } else {
        setError(e.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleTurnDone = useCallback((reportId, status = "completed") => {
    setTurns((prev) =>
      prev.map((t) => (t.id === reportId ? { ...t, status } : t))
    );
    refreshThreads();
  }, [refreshThreads]);

  // Re-run a query that failed, as a fresh turn in the current thread.
  const handleRetry = useCallback(
    (q) => submit(q),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [threadId, running]
  );

  // "Research this deeper" on a finding/conflict/gap → a follow-up in this thread.
  const handleDrillDown = useCallback(
    (text) => {
      const parent = turns[turns.length - 1];
      submit(text, {
        parentReportId: parent?.id ?? null,
        context: parent ? `Earlier in this conversation: "${parent.query}"` : null,
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [turns, threadId, running]
  );

  const handleFollowUp = (q) => {
    const parent = turns[turns.length - 1];
    submit(q, {
      parentReportId: parent?.id ?? null,
      context: parent ? `Earlier in this conversation: "${parent.query}"` : null,
    });
  };

  const reset = () => {
    setThreadId(null);
    setTurns([]);
    setError(null);
    setQuery("");
    setView("research");
  };

  const openThread = async (id) => {
    setError(null);
    setView("research");
    try {
      const t = await getThread(id);
      setThreadId(t.id);
      setTurns(
        t.reports.map((r) => ({
          id: r.id,
          query: r.query,
          status: r.status,
          mode: r.mode || "deep",
          source_scope: r.source_scope || "web",
        }))
      );
      setQuery("");
    } catch (e) {
      setError(e.message);
    }
  };

  // ---------- Auth pages (full-screen, hash-routed) ----------
  if (page === "login" || page === "signup") {
    return (
      <div className="app-bg min-h-full">
        <AuthView
          mode={page}
          onLogin={auth.login}
          onSignup={auth.signup}
          onSwitch={(m) => goto(m === "signup" ? "#/signup" : "#/login")}
          onClose={() => goto("")}
        />
      </div>
    );
  }

  // ---------- Hard gate: an account is required to use the research app ------
  // Login/signup above stay reachable while signed out; everything else funnels
  // through signup. The app is not open to anonymous visitors.
  if (!auth.user) {
    return (
      <div className="app-bg min-h-full">
        <AuthView
          mode="signup"
          gated
          onLogin={auth.login}
          onSignup={auth.signup}
          onSwitch={(m) => goto(m === "signup" ? "#/signup" : "#/login")}
        />
      </div>
    );
  }

  // Shared notice banner. A usage-cap hit (429) shows a neutral amber notice
  // with a path to bring-your-own-key; any other error shows red.
  const banner = error ? (
    <div
      className={`rounded-xl border p-3 text-sm ${
        limited
          ? "border-amber-400/30 bg-amber-400/10 text-amber-100"
          : "border-rose-500/30 bg-rose-500/10 text-rose-200"
      }`}
    >
      <div>{error}</div>
      {limited && (
        <button
          onClick={() => setShowKeys(true)}
          className="mt-2 inline-flex rounded-lg bg-gradient-to-r from-accent to-accent-cyan px-3 py-1.5 text-[13px] font-semibold text-white shadow-glow transition hover:brightness-110"
        >
          Add your API key →
        </button>
      )}
    </div>
  ) : null;

  return (
    <div className="app-bg flex min-h-full">
      {showKeys && (
        <KeySettings
          onClose={() => setShowKeys(false)}
          onSaved={() => setByok(hasByok())}
        />
      )}
      <Sidebar
        onNewResearch={reset}
        threads={threads}
        activeThreadId={view === "research" ? threadId : null}
        onSelectThread={openThread}
        onOpenGraph={() => setView("graph")}
        graphActive={view === "graph"}
        user={auth.user}
        usage={usage}
        onLogin={() => goto("#/login")}
        onSignup={() => goto("#/signup")}
        onLogout={auth.logout}
        onOpenKeys={() => setShowKeys(true)}
        byokActive={byok}
      />

      <main className="flex-1 min-w-0">
        {view === "graph" ? (
          <GraphExplorer />
        ) : !started ? (
          // ---------- Empty / hero state ----------
          <div className="mx-auto flex min-h-screen max-w-3xl flex-col items-center px-5 pb-16 pt-[13vh]">
            <div className="mb-6 animate-float">
              <Logo size={52} />
            </div>
            <h1 className="text-center text-4xl font-extrabold tracking-tight text-white sm:text-5xl">
              Research starts <span className="text-accent-cyan">deeper.</span>
            </h1>
            <p className="mt-4 mb-10 max-w-xl text-center text-[15px] leading-relaxed text-white/55">
              Five layers of agents sweep the web, read every source, cross-reference
              claims, and surface the conflicts and gaps others miss.
            </p>

            <div className="w-full animate-fade-up">
              <QueryInput
                onSubmit={submit}
                disabled={submitting}
                value={query}
                setValue={setQuery}
                mode={mode}
                setMode={setMode}
                scope={sourceScope}
                setScope={setSourceScope}
                filters={filters}
                setFilters={setFilters}
              />
            </div>

            {banner && <div className="mt-4 w-full">{banner}</div>}

            <div className="mt-6 w-full">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-white/35">
                Try a contested question
              </p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    onClick={() => {
                      setQuery(ex);
                      submit(ex);
                    }}
                    className="rounded-full border border-white/10 bg-white/[0.03] px-3.5 py-1.5 text-[12.5px] text-white/60 transition hover:border-accent/40 hover:bg-white/[0.06] hover:text-white"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>

            {contested.length > 0 && (
              <div className="mt-10 w-full">
                <button
                  onClick={() => setView("graph")}
                  className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-white/35 transition hover:text-white/60"
                >
                  Most contested in the research graph
                  <span aria-hidden>→</span>
                </button>
                <div className="space-y-2">
                  {contested.map((d) => (
                    <button
                      key={d.id}
                      onClick={() => setView("graph")}
                      className="block w-full rounded-xl border border-white/8 bg-white/[0.02] p-3 text-left transition hover:border-amber-400/25 hover:bg-white/[0.04]"
                    >
                      <div className="flex items-start gap-2 text-[13px] leading-snug text-white/75">
                        <span className="line-clamp-2 flex-1">{d.claim_a?.statement}</span>
                        <span className="mt-0.5 shrink-0 text-[10px] font-semibold uppercase text-amber-300/80">
                          vs
                        </span>
                        <span className="line-clamp-2 flex-1">{d.claim_b?.statement}</span>
                      </div>
                      <div className="mt-1.5 text-[11px] text-amber-200/60">
                        independently observed across {d.observed_count} report
                        {d.observed_count === 1 ? "" : "s"}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          // ---------- Active conversation ----------
          <div className="mx-auto max-w-4xl px-5 py-8">
            <div className="mb-6 flex items-center gap-2 md:hidden">
              <Logo size={24} />
              <span className="font-bold text-white">Deepfield</span>
            </div>

            <div className="space-y-10">
              {turns.map((t) => (
                <Turn
                  key={t.id}
                  report={t}
                  onDrillDown={handleDrillDown}
                  onDone={handleTurnDone}
                  onRetry={handleRetry}
                />
              ))}
            </div>

            {banner && <div className="mt-4">{banner}</div>}

            <div className="no-print sticky bottom-4 mt-8">
              <QueryInput
                onSubmit={handleFollowUp}
                disabled={running}
                value={query}
                setValue={setQuery}
                mode={mode}
                setMode={setMode}
                scope={sourceScope}
                setScope={setSourceScope}
                filters={filters}
                setFilters={setFilters}
                placeholder={
                  running
                    ? "Researching…"
                    : "Ask a follow-up question in this thread…"
                }
              />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
