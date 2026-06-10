import { useEffect, useRef, useState } from "react";

// Mode picker shown under the input. "chat" = Explore: a fast Haiku answer
// grounded in the accumulated graph (no new web search); "deep" = full 5-layer
// Sonnet chain; "basic" = quick single-pass Haiku answer (still web-researched).
const MODES = {
  chat: { label: "Explore", sub: "ask the graph", model: "Claude Haiku 4.5", icon: "💭" },
  deep: { label: "Deep", sub: "5-layer chain", model: "Claude Sonnet 4.6", icon: "◆" },
  basic: { label: "Basic", sub: "quick answer", model: "Claude Haiku 4.5", icon: "⚡" },
};

// Source scope picker. Keys MUST match the backend (agents/scopes.py).
// "web" is the open-web default; the rest constrain Tavily to curated
// scholarly domains.
const SCOPES = {
  web: { label: "All sources", sub: "open web + news", icon: "🌐" },
  academic: { label: "Academic journals", sub: "Nature, Science, PLOS…", icon: "🎓" },
  pubmed: { label: "PubMed / medical", sub: "NIH, WHO, Cochrane…", icon: "⚕" },
  arxiv: { label: "arXiv / preprints", sub: "arXiv, bioRxiv, SSRN…", icon: "📄" },
};

// One button showing the current source scope; click to open a menu and switch.
function ScopeDropdown({ scope, setScope, disabled }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const cur = SCOPES[scope] || SCOPES.web;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onEsc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-[12px] transition hover:border-white/20 hover:bg-white/[0.08] disabled:opacity-50"
      >
        <span>{cur.icon}</span>
        <span className="font-medium text-white">{cur.label}</span>
        <span
          className={`ml-0.5 text-[10px] text-white/40 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-20 mb-2 w-64 overflow-hidden rounded-xl border border-white/10 bg-[#0b0d16] shadow-xl">
          {Object.entries(SCOPES).map(([key, s]) => {
            const active = key === scope;
            return (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setScope(key);
                  setOpen(false);
                }}
                className={`flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition hover:bg-white/[0.06] ${
                  active ? "bg-white/[0.04]" : ""
                }`}
              >
                <span className={`mt-0.5 ${active ? "text-accent-glow" : "text-white/40"}`}>
                  {s.icon}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="text-[13px] font-medium text-white">{s.label}</span>
                  <span className="block text-[11px] text-white/40">{s.sub}</span>
                </span>
                {active && <span className="text-[12px] text-accent-glow">✓</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Advanced search filters: recency window + domain allow/blocklist. A badge on
// the button shows how many filters are active so they're never silently applied.
function FiltersDropdown({ filters, setFilters, disabled }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const f = filters || {};
  const activeCount =
    (f.yearMin ? 1 : 0) +
    (f.includeDomains?.trim() ? 1 : 0) +
    (f.excludeDomains?.trim() ? 1 : 0);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onEsc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const thisYear = new Date().getFullYear();
  const set = (patch) => setFilters({ ...f, ...patch });

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-[12px] transition hover:border-white/20 hover:bg-white/[0.08] disabled:opacity-50"
      >
        <span>⚙</span>
        <span className="font-medium text-white">Filters</span>
        {activeCount > 0 && (
          <span className="rounded-full bg-accent/30 px-1.5 text-[10px] font-semibold text-accent-glow">
            {activeCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-20 mb-2 w-72 overflow-hidden rounded-xl border border-white/10 bg-[#0b0d16] p-3 shadow-xl">
          <div className="mb-3">
            <label className="mb-1.5 block text-[11px] font-medium text-white/55">
              Published since
            </label>
            <div className="flex flex-wrap gap-1.5">
              {[null, thisYear - 1, thisYear - 3, thisYear - 5, thisYear - 10].map(
                (y) => {
                  const label = y === null ? "Any" : `${y}+`;
                  const active = (f.yearMin || null) === y;
                  return (
                    <button
                      key={label}
                      type="button"
                      onClick={() => set({ yearMin: y })}
                      className={`rounded-md px-2 py-1 text-[11px] font-medium transition ${
                        active
                          ? "bg-accent/25 text-accent-glow"
                          : "bg-white/5 text-white/55 hover:text-white/80"
                      }`}
                    >
                      {label === "Any" ? "Any time" : `Since ${y}`}
                    </button>
                  );
                }
              )}
            </div>
          </div>
          <div className="mb-3">
            <label className="mb-1.5 block text-[11px] font-medium text-white/55">
              Only these domains{" "}
              <span className="text-white/30">(comma-separated)</span>
            </label>
            <input
              value={f.includeDomains || ""}
              onChange={(e) => set({ includeDomains: e.target.value })}
              placeholder="nature.com, nih.gov"
              className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-[12px] text-white/85 placeholder:text-white/25 focus:border-accent-glow/50 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-[11px] font-medium text-white/55">
              Block these domains
            </label>
            <input
              value={f.excludeDomains || ""}
              onChange={(e) => set({ excludeDomains: e.target.value })}
              placeholder="reddit.com, medium.com"
              className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-[12px] text-white/85 placeholder:text-white/25 focus:border-accent-glow/50 focus:outline-none"
            />
          </div>
          {activeCount > 0 && (
            <button
              type="button"
              onClick={() =>
                setFilters({ yearMin: null, includeDomains: "", excludeDomains: "" })
              }
              className="mt-3 text-[11px] text-white/45 hover:text-white/70"
            >
              Clear all filters
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// One button showing the current mode; click to open a menu and switch.
function ModeDropdown({ mode, setMode, disabled }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const cur = MODES[mode] || MODES.deep;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onEsc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-[12px] transition hover:border-white/20 hover:bg-white/[0.08] disabled:opacity-50"
      >
        <span className="text-accent-glow">{cur.icon}</span>
        <span className="font-medium text-white">{cur.label}</span>
        <span className="hidden sm:inline text-white/40">· {cur.sub}</span>
        <span
          className={`ml-0.5 text-[10px] text-white/40 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-20 mb-2 w-64 overflow-hidden rounded-xl border border-white/10 bg-[#0b0d16] shadow-xl">
          {Object.entries(MODES).map(([key, m]) => {
            const active = key === mode;
            return (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setMode(key);
                  setOpen(false);
                }}
                className={`flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition hover:bg-white/[0.06] ${
                  active ? "bg-white/[0.04]" : ""
                }`}
              >
                <span className={`mt-0.5 ${active ? "text-accent-glow" : "text-white/40"}`}>
                  {m.icon}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="text-[13px] font-medium text-white">
                      {m.label}
                    </span>
                    <span className="text-[11px] text-white/40">· {m.sub}</span>
                  </span>
                  <span className="block text-[11px] text-white/40">{m.model}</span>
                </span>
                {active && <span className="text-[12px] text-accent-glow">✓</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function QueryInput({
  onSubmit,
  disabled,
  value,
  setValue,
  placeholder,
  mode = "deep",
  setMode,
  scope = "web",
  setScope,
  filters,
  setFilters,
}) {
  const submit = (e) => {
    e?.preventDefault();
    const q = (value || "").trim();
    if (!q || disabled) return;
    onSubmit(q);
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit} className="w-full">
      <div
        className={`glass rounded-2xl p-3 transition-shadow duration-300 ${
          disabled ? "opacity-90" : "hover:shadow-glow focus-within:shadow-glow"
        }`}
      >
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={placeholder || "Ask a research question…"}
          className="w-full bg-transparent px-2 py-2 text-[15px] text-white placeholder-white/35 focus:outline-none disabled:opacity-60"
        />
        <div className="mt-2 flex items-center justify-between gap-2 px-1">
          <div className="flex items-center gap-2 min-w-0">
            {setMode ? (
              <ModeDropdown mode={mode} setMode={setMode} disabled={disabled} />
            ) : (
              <span className="text-[12px] text-white/50">
                {MODES[mode]?.label} · {MODES[mode]?.model}
              </span>
            )}
            {setScope && mode !== "chat" && (
              <ScopeDropdown scope={scope} setScope={setScope} disabled={disabled} />
            )}
            {setFilters && mode !== "chat" && (
              <FiltersDropdown
                filters={filters}
                setFilters={setFilters}
                disabled={disabled}
              />
            )}
          </div>
          <button
            type="submit"
            disabled={disabled || !(value || "").trim()}
            aria-label="Run research"
            className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-accent to-accent-cyan text-white shadow-glow transition disabled:opacity-30 disabled:shadow-none hover:brightness-110 active:scale-95"
          >
            {disabled ? (
              <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.25" />
                <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
              </svg>
            ) : (
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none">
                <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </form>
  );
}
