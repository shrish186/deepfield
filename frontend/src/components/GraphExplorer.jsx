import { useEffect, useRef, useState } from "react";
import { getGraphStats, getDisagreements, getClaim, searchGraph } from "../api";
import { evidenceBand, agreementBand } from "../lib/quality";

function Stat({ label, value }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
      <div className="text-2xl font-bold text-white">{value ?? "—"}</div>
      <div className="mt-0.5 text-[11px] uppercase tracking-wider text-white/45">
        {label}
      </div>
    </div>
  );
}

const DIRECTION_STYLE = {
  strengthening: { label: "↗ Strengthening", cls: "bg-emerald-500/15 text-emerald-200" },
  weakening: { label: "↘ Weakening", cls: "bg-rose-500/15 text-rose-200" },
  stable: { label: "→ Stable", cls: "bg-white/10 text-white/60" },
  new: { label: "• New", cls: "bg-sky-500/15 text-sky-200" },
};

// Tiny inline SVG sparkline of confidence (0..1) across the snapshot series.
function Sparkline({ series, width = 240, height = 44 }) {
  const pts = (series || []).filter((p) => p && typeof p.confidence === "number");
  if (pts.length < 2) return null;
  const pad = 4;
  const xs = (i) => pad + (i * (width - 2 * pad)) / (pts.length - 1);
  const ys = (v) => height - pad - v * (height - 2 * pad);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${xs(i).toFixed(1)},${ys(p.confidence).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} className="overflow-visible">
      <path d={d} fill="none" stroke="url(#spark)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={xs(pts.length - 1)} cy={ys(last.confidence)} r="3" fill="#34d399" />
      <defs>
        <linearGradient id="spark" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#60a5fa" />
          <stop offset="100%" stopColor="#34d399" />
        </linearGradient>
      </defs>
    </svg>
  );
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

// Detail drawer for one canonical claim: its evolution over time (the moat's
// "is the evidence changing?" view), plus sources and linked disagreements.
function ClaimModal({ claimId, onClose }) {
  const [claim, setClaim] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setClaim(null);
    setError(null);
    (async () => {
      try {
        const c = await getClaim(claimId);
        if (!cancelled) setClaim(c);
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [claimId]);

  const dir = DIRECTION_STYLE[claim?.direction] || DIRECTION_STYLE.new;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 px-4 py-10 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="glass w-full max-w-2xl rounded-2xl p-6 animate-fade-up"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-[15px] font-semibold leading-relaxed text-white">
            {claim?.statement || "Loading…"}
          </h2>
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg px-2 py-1 text-white/50 transition hover:bg-white/10 hover:text-white"
          >
            ✕
          </button>
        </div>

        {error && <div className="text-sm text-rose-300">Couldn’t load claim: {error}</div>}

        {claim && (
          <>
            <div className="mb-5 flex flex-wrap items-center gap-2.5 text-[12px]">
              <span className={`rounded-full px-2.5 py-1 font-medium ${dir.cls}`}>
                {dir.label}
              </span>
              <span className={`font-medium ${evidenceBand(claim.support_count).cls}`}>
                {evidenceBand(claim.support_count).label}
              </span>
              <span className="text-white/50">
                {claim.support_count} source(s) · {claim.report_count} report(s)
              </span>
              {claim.disagreements?.length > 0 && (
                <span className={`font-medium ${agreementBand(true).cls}`}>
                  · {agreementBand(true).label}
                </span>
              )}
            </div>

            {/* Evolution timeline */}
            <div className="mb-5 rounded-xl border border-white/8 bg-white/[0.02] p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-white/45">
                  How the evidence evolved
                </h3>
                <Sparkline series={claim.evolution} />
              </div>
              {(!claim.evolution || claim.evolution.length === 0) ? (
                <p className="text-[12.5px] text-white/40">No history recorded yet.</p>
              ) : (
                <div className="space-y-1.5">
                  {claim.evolution.map((p, i) => (
                    <div key={i} className="flex items-center gap-3 text-[12.5px]">
                      <span className="w-24 shrink-0 text-white/45">{fmtDate(p.observed_at)}</span>
                      <span className="text-white/70">{p.support_count} source(s)</span>
                      <span className="text-white/30">·</span>
                      <span className={`font-medium ${evidenceBand(p.support_count).cls}`}>
                        {evidenceBand(p.support_count).label}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Linked disagreements */}
            {claim.disagreements?.length > 0 && (
              <div className="mb-5">
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/45">
                  Contested against
                </h3>
                <div className="space-y-2">
                  {claim.disagreements.map((d) => (
                    <div key={d.id} className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-3">
                      <div className="text-[13px] text-white/80">{d.other_claim?.statement}</div>
                      <div className="mt-1 text-[11px] text-amber-200/70">seen ×{d.observed_count}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Sources */}
            {claim.sources?.length > 0 && (
              <div>
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-white/45">
                  Backing sources ({claim.sources.length})
                </h3>
                <div className="space-y-1">
                  {claim.sources.map((s) => (
                    <a
                      key={s.id}
                      href={s.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block truncate text-[12.5px] text-sky-300/80 hover:text-sky-200"
                    >
                      {s.title || s.url}
                      {s.domain && <span className="text-white/30"> · {s.domain}</span>}
                    </a>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// One opposing position in a controversy map: a claim box with its evidence
// strength and source count, wired to the split above it by a connector line.
function PositionBox({ side, claim, onSelectClaim }) {
  if (!claim) return null;
  const ev = evidenceBand(claim.support_count);
  const tone =
    side === "left"
      ? "border-sky-400/25 bg-sky-500/[0.06] hover:border-sky-400/50"
      : "border-violet-400/25 bg-violet-500/[0.06] hover:border-violet-400/50";
  return (
    <div className="relative flex flex-1 flex-col items-center">
      {/* vertical drop from the horizontal branch into this box */}
      <span className="h-4 w-px bg-white/15" aria-hidden />
      <button
        onClick={() => claim.id && onSelectClaim(claim.id)}
        className={`w-full rounded-xl border p-3 text-left transition ${tone}`}
      >
        <div className="text-[13px] leading-relaxed text-white/90">
          {claim.statement}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-1.5 text-[11px] text-white/45">
          <span className={`font-semibold ${ev.cls}`}>{ev.label}</span>
          <span>· {claim.support_count} source(s)</span>
          <span className="text-accent/70">· evolution →</span>
        </div>
      </button>
    </div>
  );
}

// One disagreement rendered as a small "controversy map": a center node (the
// point of contention) fanning out to the two opposing positions, each labelled
// with its evidence strength. The trunk badge shows how many independent reports
// surfaced it — the moat metric.
function DisagreementCard({ edge, onSelectClaim }) {
  return (
    <div className="glass rounded-2xl p-5 animate-fade-up">
      {edge.description && (
        <p className="mb-4 text-[13.5px] leading-relaxed text-white/70">
          {edge.description}
        </p>
      )}

      {/* Map: contention node → branch → two positions */}
      <div className="flex flex-col items-center">
        <div
          className="inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/15 px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-amber-200"
          title="How many independent reports surfaced this disagreement"
        >
          ⚖️ Disagreement
          <span className="rounded-full bg-amber-500/25 px-1.5 font-mono">
            seen ×{edge.observed_count}
          </span>
        </div>

        {/* trunk down to the split */}
        <span className="h-4 w-px bg-white/15" aria-hidden />
        {/* horizontal branch connecting the two sides */}
        <span className="h-px w-1/2 bg-white/15" aria-hidden />

        <div className="flex w-full items-stretch gap-3">
          <PositionBox side="left" claim={edge.claim_a} onSelectClaim={onSelectClaim} />
          <PositionBox side="right" claim={edge.claim_b} onSelectClaim={onSelectClaim} />
        </div>
      </div>
    </div>
  );
}

// One topic-search hit: a single canonical claim, its support, whether it's
// contested, and how closely it matched the query. Opens the same ClaimModal.
function SearchResultCard({ hit, onSelectClaim }) {
  return (
    <button
      onClick={() => hit.id && onSelectClaim(hit.id)}
      className="glass block w-full rounded-2xl p-4 text-left animate-fade-up transition hover:border-accent/40 hover:bg-white/[0.05]"
    >
      <div className="text-[14px] leading-relaxed text-white/85">
        {hit.statement}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-white/45">
        <span className={`font-medium ${evidenceBand(hit.support_count).cls}`}>
          {evidenceBand(hit.support_count).label}
        </span>
        <span className="text-white/20">·</span>
        <span>{hit.support_count} source(s)</span>
        <span className="text-white/20">·</span>
        <span>{hit.report_count} report(s)</span>
        {hit.disagreement_count > 0 && (
          <span className="rounded-full bg-amber-500/15 px-2 py-0.5 font-medium text-amber-200">
            ⚖️ contested ×{hit.disagreement_count}
          </span>
        )}
        {typeof hit.similarity === "number" && (
          <span className="ml-auto font-mono text-white/30">
            {Math.round(hit.similarity * 100)}% match
          </span>
        )}
      </div>
    </button>
  );
}

export default function GraphExplorer() {
  const [stats, setStats] = useState(null);
  const [edges, setEdges] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedClaim, setSelectedClaim] = useState(null);

  // Topic search overlays the default "trending disagreements" list.
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null); // null = not searching
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const debounce = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [s, d] = await Promise.all([getGraphStats(), getDisagreements(50)]);
        if (cancelled) return;
        setStats(s);
        setEdges(d);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Debounced live search; clearing the box restores the trending view.
  useEffect(() => {
    const q = query.trim();
    if (debounce.current) clearTimeout(debounce.current);
    if (!q) {
      setResults(null);
      setSearching(false);
      setSearchError(null);
      return;
    }
    setSearching(true);
    debounce.current = setTimeout(async () => {
      try {
        const data = await searchGraph(q, 25);
        setResults(data.results || []);
        setSearchError(null);
      } catch (e) {
        setSearchError(e.message);
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => debounce.current && clearTimeout(debounce.current);
  }, [query]);

  return (
    <div className="mx-auto max-w-4xl px-5 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-white">
          The disagreement graph
        </h1>
        <p className="mt-1.5 text-[14px] leading-relaxed text-white/55">
          Every deep report contributes its canonical claims and the
          contradictions between them. The same disagreement found across
          independent reports compounds here — a structured map of where the
          evidence conflicts. Click any claim to see how its evidence has
          evolved over time.
        </p>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Canonical claims" value={stats?.canonical_claims} />
        <Stat label="Disagreements" value={stats?.disagreements} />
        <Stat label="Sources" value={stats?.canonical_sources} />
        <Stat label="Evidence links" value={stats?.evidence_edges} />
      </div>

      {/* Topic search across the whole graph */}
      <div className="relative mb-8">
        <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-white/35">
          ⌕
        </span>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the graph by topic — e.g. creatine, inflation, nuclear energy"
          className="w-full rounded-xl border border-white/10 bg-white/[0.03] py-3 pl-10 pr-10 text-[14px] text-white placeholder:text-white/30 outline-none transition focus:border-accent/50 focus:bg-white/[0.05]"
        />
        {query && (
          <button
            onClick={() => setQuery("")}
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg px-2 py-1 text-white/40 transition hover:bg-white/10 hover:text-white"
          >
            ✕
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
          Couldn’t load the graph: {error}
        </div>
      )}

      {loading && !error && (
        <div className="glass rounded-2xl p-6 text-sm text-white/40 animate-pulse-soft">
          Loading the graph…
        </div>
      )}

      {/* Search results replace the trending list while a query is active. */}
      {results !== null ? (
        <div>
          <div className="mb-3 flex items-center gap-2 text-[12px] text-white/45">
            {searching ? (
              <span className="animate-pulse-soft">Searching…</span>
            ) : searchError ? (
              <span className="text-rose-300">Search failed: {searchError}</span>
            ) : (
              <span>
                {results.length} claim(s) related to “{query.trim()}”
              </span>
            )}
          </div>
          {!searching && !searchError && results.length === 0 ? (
            <div className="glass rounded-2xl p-6 text-sm text-white/50">
              No related claims in the graph yet. Try a broader topic, or run a
              deep report on this to start building it out.
            </div>
          ) : (
            <div className="space-y-3">
              {results.map((hit) => (
                <SearchResultCard
                  key={hit.id}
                  hit={hit}
                  onSelectClaim={setSelectedClaim}
                />
              ))}
            </div>
          )}
        </div>
      ) : (
        <>
          {!loading && !error && edges.length === 0 && (
            <div className="glass rounded-2xl p-6 text-sm text-white/50">
              No disagreements recorded yet. Run a deep report (with a Voyage API
              key configured) and contradictions will start accumulating here.
            </div>
          )}

          <div className="space-y-3">
            {edges.map((e) => (
              <DisagreementCard key={e.id} edge={e} onSelectClaim={setSelectedClaim} />
            ))}
          </div>
        </>
      )}

      {selectedClaim != null && (
        <ClaimModal claimId={selectedClaim} onClose={() => setSelectedClaim(null)} />
      )}
    </div>
  );
}
