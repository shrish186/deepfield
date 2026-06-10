import { useEffect, useState } from "react";
import { compareSources } from "../api";

// Head-to-head comparison of two sources. The backend runs an LLM that returns
// agreements, conflicts, and a verdict on which paper carries stronger evidence.
export default function CompareModal({ sourceA, sourceB, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    (async () => {
      try {
        const res = await compareSources(sourceA.id, sourceB.id);
        if (!cancelled) setData(res);
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sourceA.id, sourceB.id]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="glass max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-white/10 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 className="text-[15px] font-semibold text-white/90">
            ⚖️ Comparing two sources
          </h2>
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg border border-white/10 px-2.5 py-1 text-[12px] text-white/60 hover:bg-white/5"
          >
            Close
          </button>
        </div>

        <div className="mb-5 grid gap-3 md:grid-cols-2">
          {[sourceA, sourceB].map((s, i) => (
            <div key={s.id} className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
              <div className="mb-1 text-[10px] uppercase tracking-widest text-white/40">
                Source {i === 0 ? "A" : "B"}
              </div>
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer"
                className="text-[12.5px] font-medium text-white/85 hover:text-accent-glow"
              >
                {s.title}
              </a>
            </div>
          ))}
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-[13px] text-rose-200">
            Comparison failed: {error}
          </div>
        )}

        {!data && !error && (
          <div className="animate-pulse-soft py-10 text-center text-[13px] text-white/40">
            Analyzing both papers head-to-head…
          </div>
        )}

        {data && (
          <div className="space-y-4">
            {data.verdict && (
              <div className="rounded-xl border border-accent/25 bg-accent/[0.06] p-4">
                <div className="mb-1 text-[10px] uppercase tracking-widest text-accent-glow">
                  Verdict
                </div>
                <p className="text-[13.5px] leading-relaxed text-white/85">{data.verdict}</p>
                {data.stronger_reason && (
                  <p className="mt-2 text-[12.5px] leading-relaxed text-white/55">
                    {data.stronger_reason}
                  </p>
                )}
              </div>
            )}

            <CompareList
              title="Where they agree"
              icon="✓"
              items={data.agreements}
              cls="text-emerald-200/90"
            />
            <CompareList
              title="Where they conflict"
              icon="✗"
              items={data.conflicts}
              cls="text-amber-200/90"
            />
          </div>
        )}
      </div>
    </div>
  );
}

function CompareList({ title, icon, items, cls }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-wider text-white/60">
        {title}
      </h3>
      <ul className="space-y-2">
        {items.map((it, i) => (
          <li key={i} className="flex gap-2 text-[13px] leading-relaxed">
            <span className={`shrink-0 ${cls}`}>{icon}</span>
            <span className="text-white/75">{it}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
