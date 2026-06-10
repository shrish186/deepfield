const LAYERS = [
  { n: 1, label: "Breadth Sweep", sub: "search" },
  { n: 2, label: "Deep Dives", sub: "read" },
  { n: 3, label: "Cross-Reference", sub: "synthesize" },
  { n: 4, label: "Conflicts & Gaps", sub: "audit" },
  { n: 5, label: "Synthesis", sub: "report" },
];

// Derives current progress from the live event stream.
export default function PipelineProgress({ events, done }) {
  const maxLayer = events.reduce(
    (m, e) => (typeof e.layer === "number" && e.layer > m ? e.layer : m),
    0
  );

  return (
    <div className="flex items-center gap-1.5 sm:gap-2">
      {LAYERS.map((l, i) => {
        const active = !done && maxLayer === l.n;
        const complete = done || maxLayer > l.n;
        const state = complete ? "complete" : active ? "active" : "idle";
        return (
          <div key={l.n} className="flex items-center gap-1.5 sm:gap-2 flex-1">
            <div className="flex flex-col gap-1.5 flex-1 min-w-0">
              <div
                className={`h-1 rounded-full transition-all duration-500 ${
                  state === "complete"
                    ? "bg-gradient-to-r from-accent to-accent-cyan"
                    : state === "active"
                    ? "bg-gradient-to-r from-accent to-accent-cyan animate-pulse-soft"
                    : "bg-white/10"
                }`}
              />
              <div className="flex items-baseline gap-1.5 min-w-0">
                <span
                  className={`text-[10px] font-mono shrink-0 ${
                    state === "idle" ? "text-white/30" : "text-accent-glow"
                  }`}
                >
                  L{l.n}
                </span>
                <span
                  className={`text-[11px] truncate ${
                    state === "idle"
                      ? "text-white/30"
                      : state === "active"
                      ? "text-white"
                      : "text-white/60"
                  }`}
                >
                  {l.label}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
