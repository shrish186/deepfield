import { credibilityBand, evidenceBand, sourceTypeBadge } from "../lib/quality";

// Short author display: "Jane Smith et al." for multi-author, the single name otherwise.
function authorLabel(authors) {
  if (!authors) return null;
  const first = authors.split(";")[0].trim();
  return authors.includes(";") ? `${first} et al.` : first;
}

export default function SourceCard({ source, selectable = false, selected = false, onToggle }) {
  const topClaim = source.claims && source.claims[0];
  const cred = credibilityBand(source.credibility_score);
  const stype = sourceTypeBadge(source.source_type);
  const author = authorLabel(source.authors);

  return (
    <div
      className={`group rounded-xl border p-4 transition-all ${
        selected
          ? "border-accent-glow/50 bg-accent-glow/[0.06]"
          : "border-white/8 bg-white/[0.02] hover:border-white/15 hover:bg-white/[0.04]"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <a
          href={source.url}
          target="_blank"
          rel="noreferrer"
          className="text-[13.5px] font-medium text-white/90 hover:text-accent-glow break-words leading-snug"
        >
          {source.title}
        </a>
        <span
          className={`shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-medium ${cred.cls}`}
          title={`Source credibility: ${cred.label}`}
        >
          {cred.label}
        </span>
      </div>

      {/* Trust / metadata badge row */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px]">
        <span className={`rounded border px-1.5 py-0.5 font-medium ${stype.cls}`}>
          {stype.label}
        </span>
        {source.peer_reviewed && (
          <span
            className="rounded border border-emerald-500/25 bg-emerald-500/10 px-1.5 py-0.5 font-medium text-emerald-300"
            title="Published in a peer-reviewed venue"
          >
            ✓ Peer-reviewed
          </span>
        )}
        {source.retracted && (
          <span
            className="rounded border border-rose-500/40 bg-rose-500/15 px-1.5 py-0.5 font-semibold text-rose-300"
            title="This paper appears to have been retracted"
          >
            ⚠ Retracted
          </span>
        )}
        {author && (
          <span className="rounded bg-white/5 px-1.5 py-0.5 text-white/55">{author}</span>
        )}
        {source.year && (
          <span className="rounded bg-white/5 px-1.5 py-0.5 text-white/55">{source.year}</span>
        )}
        {source.venue && (
          <span
            className="max-w-[160px] truncate rounded bg-white/5 px-1.5 py-0.5 text-white/55"
            title={source.venue}
          >
            {source.venue}
          </span>
        )}
        {source.citation_count != null && (
          <span
            className="rounded bg-white/5 px-1.5 py-0.5 text-white/55"
            title="Citations (Semantic Scholar)"
          >
            {source.citation_count.toLocaleString()} cites
          </span>
        )}
      </div>

      <div className="text-[11px] text-white/35 mt-1.5 break-all">
        {source.doi
          ? `doi:${source.doi}`
          : source.url.replace(/^https?:\/\//, "").split("/")[0]}
      </div>

      {topClaim && (
        <div className="mt-3 border-t border-white/6 pt-3 text-[12.5px]">
          <span className="text-white/40">Key claim · </span>
          <span className="text-white/75">{topClaim.claim_text}</span>
          <div className="mt-1.5 flex items-center gap-2 text-[10px] text-white/40">
            <span className={`rounded bg-white/5 px-1.5 py-0.5 font-medium ${evidenceBand(topClaim.support_count).cls}`}>
              {evidenceBand(topClaim.support_count).label}
            </span>
            <span className="rounded bg-white/5 px-1.5 py-0.5">
              {topClaim.support_count} source{topClaim.support_count === 1 ? "" : "s"}
            </span>
          </div>
        </div>
      )}

      {selectable && (
        <button
          onClick={() => onToggle?.(source)}
          className={`mt-3 w-full rounded-lg border px-2 py-1.5 text-[11px] font-medium transition-colors ${
            selected
              ? "border-accent-glow/50 bg-accent-glow/15 text-accent-glow"
              : "border-white/10 bg-white/[0.02] text-white/50 hover:border-white/20 hover:text-white/75"
          }`}
        >
          {selected ? "✓ Selected to compare" : "Select to compare"}
        </button>
      )}
    </div>
  );
}
