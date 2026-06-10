export default function ConflictCard({ conflict, onDrill }) {
  return (
    <div className="group rounded-xl border border-amber-500/25 bg-amber-500/[0.06] p-4 transition-colors hover:border-amber-500/40">
      <div className="flex items-center gap-2 mb-2">
        <span className="grid h-5 w-5 place-items-center rounded-md bg-amber-500/20 text-[11px]">
          ⚠️
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-wider text-amber-300">
          {conflict.topic || "Sources disagree"}
        </span>
      </div>
      <p className="text-[13.5px] text-amber-50/90 leading-relaxed">
        {conflict.description}
      </p>
      {onDrill && (
        <DrillButton
          onClick={() =>
            onDrill(`Resolve this contradiction: ${conflict.description}`)
          }
        />
      )}
    </div>
  );
}

function DrillButton({ onClick }) {
  return (
    <button
      onClick={onClick}
      className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[11.5px] text-white/55 transition hover:border-accent/40 hover:text-white hover:bg-white/[0.07]"
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
        <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
      Research this deeper
    </button>
  );
}
