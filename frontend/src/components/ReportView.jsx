import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getReport,
  getSources,
  getConflicts,
  getGaps,
  getCitations,
  uploadPaper,
} from "../api";
import ConflictCard from "./ConflictCard";
import SourceCard from "./SourceCard";
import CompareModal from "./CompareModal";
import CommentsPanel from "./CommentsPanel";

// Short labels for the non-web source scopes, shown as a chip on the report so
// it's clear which corpus was searched. Keys match the backend (scopes.py).
const SCOPE_CHIPS = {
  academic: "🎓 Academic journals",
  pubmed: "⚕ PubMed / medical",
  arxiv: "📄 arXiv / preprints",
};

function Markdown({ children }) {
  return (
    <div className="prose-deepfield text-[14.5px] leading-relaxed text-white/80">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

// Collapsible section — keeps the page scannable. The headline answer stays
// open; supporting detail (conflicts, gaps, sources) is tucked away with a
// count so it's discoverable without burying the reader in text.
function Collapsible({ title, count, icon, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="glass rounded-2xl overflow-hidden animate-fade-up">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition hover:bg-white/[0.03]"
      >
        <span className="flex items-center gap-2.5">
          {icon && <span className="text-[15px]">{icon}</span>}
          <span className="text-[14px] font-semibold text-white/90">{title}</span>
          {count != null && (
            <span className="rounded-full bg-white/8 px-2 py-0.5 text-[11px] font-mono text-white/50">
              {count}
            </span>
          )}
        </span>
        <span
          className={`text-white/40 transition-transform ${open ? "rotate-90" : ""}`}
        >
          ▸
        </span>
      </button>
      {open && <div className="border-t border-white/8 px-5 py-4">{children}</div>}
    </section>
  );
}

// Report-level actions: print/PDF, shareable link, and citation export. These are
// the "make it usable by a real researcher" touches — exporting and sharing a
// finished report.
function ReportToolbar({ reportId }) {
  const [copied, setCopied] = useState(false);
  const [citeOpen, setCiteOpen] = useState(false);
  const [citeFmt, setCiteFmt] = useState("apa");
  const [citeText, setCiteText] = useState("");
  const [citeBusy, setCiteBusy] = useState(false);
  const [citeCopied, setCiteCopied] = useState(false);

  const copyLink = async () => {
    const url = `${window.location.origin}${window.location.pathname}#/report/${reportId}`;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      /* clipboard may be blocked; still flag visually */
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const loadCitations = async (fmt) => {
    setCiteFmt(fmt);
    setCiteBusy(true);
    try {
      const res = await getCitations(reportId, fmt);
      setCiteText(res.content || "(no citable sources)");
    } catch (e) {
      setCiteText(`Failed to load citations: ${e.message}`);
    } finally {
      setCiteBusy(false);
    }
  };

  const openCite = () => {
    const next = !citeOpen;
    setCiteOpen(next);
    if (next && !citeText) loadCitations(citeFmt);
  };

  const copyCite = async () => {
    try {
      await navigator.clipboard.writeText(citeText);
      setCiteCopied(true);
      setTimeout(() => setCiteCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="no-print flex flex-wrap items-center gap-2">
      <button
        onClick={() => window.print()}
        className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-1.5 text-[12px] font-medium text-white/65 transition hover:border-white/20 hover:text-white/90"
      >
        ⬇ Export PDF
      </button>
      <button
        onClick={copyLink}
        className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-1.5 text-[12px] font-medium text-white/65 transition hover:border-white/20 hover:text-white/90"
      >
        {copied ? "✓ Link copied" : "🔗 Copy share link"}
      </button>
      <div className="relative">
        <button
          onClick={openCite}
          className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-1.5 text-[12px] font-medium text-white/65 transition hover:border-white/20 hover:text-white/90"
        >
          ❝ Cite ▾
        </button>
        {citeOpen && (
          <div className="absolute left-0 top-full z-30 mt-2 w-[360px] max-w-[80vw] rounded-xl border border-white/12 bg-[#11131a] p-3 shadow-2xl">
            <div className="mb-2 flex gap-1.5">
              {["bibtex", "apa", "mla"].map((f) => (
                <button
                  key={f}
                  onClick={() => loadCitations(f)}
                  className={`rounded-md px-2 py-1 text-[11px] font-medium uppercase transition ${
                    citeFmt === f
                      ? "bg-accent/25 text-accent-glow"
                      : "bg-white/5 text-white/50 hover:text-white/80"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
            <textarea
              readOnly
              value={citeBusy ? "Loading…" : citeText}
              rows={7}
              className="w-full resize-none rounded-lg border border-white/10 bg-black/30 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-white/75 focus:outline-none"
            />
            <button
              onClick={copyCite}
              className="mt-2 rounded-md border border-white/10 px-2.5 py-1 text-[11px] text-white/60 hover:bg-white/5"
            >
              {citeCopied ? "✓ Copied" : "Copy all"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ReportView({ reportId, onDrillDown, onRetry, onStatus }) {
  const [report, setReport] = useState(null);
  const [sources, setSources] = useState([]);
  const [conflicts, setConflicts] = useState([]);
  const [gaps, setGaps] = useState([]);
  const [error, setError] = useState(null);

  // Compare mode + upload state.
  const [compareMode, setCompareMode] = useState(false);
  const [compareSel, setCompareSel] = useState([]); // up to 2 source objects
  const [comparePair, setComparePair] = useState(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadMsg, setUploadMsg] = useState("");
  const fileRef = useRef(null);

  const loadSources = async () => {
    try {
      setSources(await getSources(reportId));
    } catch {
      /* non-fatal */
    }
  };

  useEffect(() => {
    if (!reportId) return;
    let cancelled = false;
    // reset per-report UI state
    setCompareMode(false);
    setCompareSel([]);
    setComparePair(null);
    setUploadMsg("");
    (async () => {
      try {
        const [r, s, c, g] = await Promise.all([
          getReport(reportId),
          getSources(reportId),
          getConflicts(reportId),
          getGaps(reportId),
        ]);
        if (cancelled) return;
        setReport(r);
        setSources(s);
        setConflicts(c);
        setGaps(g);
        onStatus?.(r.status);
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reportId, onStatus]);

  const toggleCompare = (src) => {
    setCompareSel((prev) => {
      const exists = prev.find((p) => p.id === src.id);
      if (exists) return prev.filter((p) => p.id !== src.id);
      const next = [...prev, src].slice(-2); // keep last two
      if (next.length === 2) setComparePair(next);
      return next;
    });
  };

  const onUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadBusy(true);
    setUploadMsg("");
    try {
      const src = await uploadPaper(reportId, file);
      setUploadMsg(`✓ Added "${src.title}"`);
      await loadSources();
    } catch (err) {
      setUploadMsg(`Upload failed: ${err.message}`);
    } finally {
      setUploadBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  if (error) {
    return (
      <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
        Failed to load report: {error}
      </div>
    );
  }

  if (!report) {
    return (
      <div className="glass rounded-2xl p-6 text-sm text-white/40 animate-pulse-soft">
        Assembling report…
      </div>
    );
  }

  if (report.status === "failed") {
    return (
      <div className="rounded-2xl border border-amber-500/30 bg-amber-500/[0.07] p-6">
        <div className="text-[15px] font-semibold text-amber-200">
          This research didn’t finish
        </div>
        <p className="mt-1.5 text-sm leading-relaxed text-white/60">
          Something interrupted the run before it could complete. Nothing was
          saved for this question — you can try it again.
        </p>
        {onRetry && (
          <button
            onClick={() => onRetry(report.query)}
            className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3.5 py-2 text-[13px] font-medium text-amber-100 transition hover:bg-amber-500/20"
          >
            Try this research again
          </button>
        )}
      </div>
    );
  }

  const isBasic = report.mode === "basic";
  const isChat = report.mode === "chat";
  const sectionByType = Object.fromEntries(
    (report.sections || []).map((s) => [s.section_type, s])
  );
  const answer = sectionByType.executive_summary?.content;
  const keyPoints = sectionByType.key_findings?.content;
  const priorKnowledge = sectionByType.prior_knowledge?.content;
  const evidenceTest = sectionByType.evidence_test?.content;

  return (
    <div className="space-y-3">
      {comparePair && (
        <CompareModal
          sourceA={comparePair[0]}
          sourceB={comparePair[1]}
          onClose={() => {
            setComparePair(null);
            setCompareSel([]);
          }}
        />
      )}

      {/* Toolbar — export / share / cite. Hidden when printing. */}
      {!isChat && <ReportToolbar reportId={reportId} />}

      {/* Prior knowledge — what the disagreement graph already established from
          earlier reports. Sits above the answer so the reader sees the
          accumulated context first. Only shown when the graph had something. */}
      {priorKnowledge && (
        <section className="rounded-2xl border border-violet-400/25 bg-violet-500/[0.06] p-5 animate-fade-up">
          <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-widest text-violet-200/80">
            <span>🧠 What prior research established</span>
          </div>
          <Markdown>{priorKnowledge}</Markdown>
        </section>
      )}

      {/* Headline answer — the one thing everyone reads. */}
      <div className="rounded-2xl border border-accent/25 bg-accent/[0.06] p-6 animate-fade-up">
        <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-widest text-accent-glow">
          <span>{isChat ? "💭 Explore" : isBasic ? "⚡ Quick answer" : "◆ Answer"}</span>
          {!isChat && SCOPE_CHIPS[report.source_scope] && (
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-medium normal-case tracking-normal text-white/60">
              {SCOPE_CHIPS[report.source_scope]}
            </span>
          )}
        </div>
        {answer ? (
          <Markdown>{answer}</Markdown>
        ) : (
          <p className="text-sm text-white/50">No answer was generated.</p>
        )}
      </div>

      {/* Key points — short, scannable. */}
      {keyPoints && (
        <section className="glass rounded-2xl p-5 animate-fade-up">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-[13px] font-semibold uppercase tracking-wider text-white/70">
              Key points
            </h2>
            <span
              className="text-[10px] text-white/35"
              title="Confidence reflects how many independent sources back a finding: High ≥3 · Medium 2 · Low 1"
            >
              confidence = source count ⓘ
            </span>
          </div>
          <Markdown>{keyPoints}</Markdown>
        </section>
      )}

      {/* What would change this conclusion — the robustness / falsifiability test. */}
      {evidenceTest && (
        <section className="glass rounded-2xl p-5 animate-fade-up">
          <h2 className="mb-1 text-[13px] font-semibold uppercase tracking-wider text-white/70">
            🧪 What would change this conclusion
          </h2>
          <p className="mb-3 text-[11.5px] text-white/40">
            Concrete evidence that — if it surfaced — would overturn the answer.
            A read on how settled this really is.
          </p>
          <Markdown>{evidenceTest}</Markdown>
        </section>
      )}

      {/* Everything below is supporting detail — collapsed to keep it readable. */}
      {conflicts.length > 0 && (
        <Collapsible
          title="Where sources disagree"
          count={conflicts.length}
          icon="⚖️"
        >
          <div className="space-y-3">
            {conflicts.map((c) => (
              <ConflictCard key={c.id} conflict={c} onDrill={onDrillDown} />
            ))}
          </div>
        </Collapsible>
      )}

      {gaps.length > 0 && (
        <Collapsible
          title="Open questions & gaps"
          count={gaps.length}
          icon="❓"
        >
          <ul className="space-y-2.5">
            {gaps.map((g) => (
              <li key={g.id} className="flex gap-2.5 text-[14px]">
                <span className="shrink-0">{g.kind === "gap" ? "🕳️" : "❓"}</span>
                <span className="flex-1 min-w-0">
                  <span className="text-white/80 leading-relaxed">
                    {g.description}
                  </span>
                  {onDrillDown && (
                    <button
                      onClick={() =>
                        onDrillDown(
                          `${
                            g.kind === "gap"
                              ? "Investigate this gap"
                              : "Answer this open question"
                          }: ${g.description}`
                        )
                      }
                      className="mt-1.5 flex items-center gap-1 text-[11.5px] text-accent-glow/80 transition hover:text-accent-glow"
                    >
                      Research this deeper →
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Collapsible>
      )}

      {sources.length > 0 && (
        <Collapsible title="Sources" count={sources.length} icon="🔗">
          <div className="no-print mb-3 flex flex-wrap items-center gap-2">
            <button
              onClick={() => {
                setCompareMode((v) => !v);
                setCompareSel([]);
              }}
              className={`rounded-lg border px-3 py-1.5 text-[12px] font-medium transition ${
                compareMode
                  ? "border-accent-glow/50 bg-accent-glow/15 text-accent-glow"
                  : "border-white/10 bg-white/[0.02] text-white/60 hover:border-white/20"
              }`}
            >
              {compareMode ? "✕ Exit compare" : "⚖️ Compare two papers"}
            </button>
            {compareMode && (
              <span className="text-[11.5px] text-white/45">
                Select two sources to compare ({compareSel.length}/2)
              </span>
            )}

            <label className="ml-auto cursor-pointer rounded-lg border border-white/10 bg-white/[0.02] px-3 py-1.5 text-[12px] font-medium text-white/60 transition hover:border-white/20 hover:text-white/90">
              {uploadBusy ? "Analyzing PDF…" : "＋ Add your paper (PDF)"}
              <input
                ref={fileRef}
                type="file"
                accept="application/pdf,.pdf"
                onChange={onUpload}
                disabled={uploadBusy}
                className="hidden"
              />
            </label>
          </div>
          {uploadMsg && (
            <div className="mb-3 text-[11.5px] text-white/55">{uploadMsg}</div>
          )}

          <div className="grid gap-3 md:grid-cols-2">
            {sources.map((s) => (
              <SourceCard
                key={s.id}
                source={s}
                selectable={compareMode}
                selected={!!compareSel.find((p) => p.id === s.id)}
                onToggle={toggleCompare}
              />
            ))}
          </div>
        </Collapsible>
      )}

      {/* Team notes / annotations / assignments. */}
      {!isChat && (
        <Collapsible title="Team notes & follow-ups" icon="💬">
          <CommentsPanel reportId={reportId} />
        </Collapsible>
      )}
    </div>
  );
}
