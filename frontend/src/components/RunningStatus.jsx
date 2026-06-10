import { useEffect, useState } from "react";
import AgentFeed from "./AgentFeed";

// Plain-English phase for each layer + a rough duration weight (seconds) used to
// derive a smooth progress bar and a falling ETA without per-run instrumentation.
const DEEP_PHASES = [
  { layer: 1, label: "Sweeping the web for sources", weight: 15 },
  { layer: 2, label: "Reading every source in depth", weight: 70 },
  { layer: 3, label: "Cross-referencing claims across sources", weight: 45 },
  { layer: 4, label: "Hunting for contradictions & gaps", weight: 45 },
  { layer: 5, label: "Writing the structured report", weight: 25 },
];
const BASIC_PHASES = [
  { layer: 1, label: "Searching the web", weight: 10 },
  { layer: 5, label: "Writing a clear answer", weight: 12 },
];
const CHAT_PHASES = [{ layer: 5, label: "Exploring the graph", weight: 6 }];

function fmtEta(sec) {
  if (sec <= 0) return "almost done";
  const s = Math.round(sec);
  if (s < 60) return `~${s}s left`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `~${m}m ${r}s left` : `~${m}m left`;
}

export default function RunningStatus({ events, done, connected, mode }) {
  const [showDetails, setShowDetails] = useState(false);

  const PHASES =
    mode === "chat" ? CHAT_PHASES : mode === "basic" ? BASIC_PHASES : DEEP_PHASES;
  const TOTAL = PHASES.reduce((s, p) => s + p.weight, 0);

  const maxLayer = events.reduce(
    (m, e) => (typeof e.layer === "number" && e.layer > m ? e.layer : m),
    0
  );
  // Map the latest emitted layer to its phase; fall back to the first phase
  // while we're still spinning up (layer 0 = orchestrator).
  let idx = PHASES.findIndex((p) => p.layer === maxLayer);
  if (idx === -1) idx = maxLayer === 0 ? 0 : PHASES.length - 1;

  const elapsedWeight =
    PHASES.slice(0, idx).reduce((s, p) => s + p.weight, 0) +
    (PHASES[idx]?.weight ?? 0) * 0.5;
  const remainingWeight = TOTAL - elapsedWeight;

  const progress = done
    ? 100
    : Math.min(96, Math.round((elapsedWeight / TOTAL) * 100));
  const eta = done ? 0 : remainingWeight;

  // Latest line from the feed, shown as a subtle live subtitle.
  const lastMsg = events.length ? events[events.length - 1].message : null;
  const spinningUpLabel =
    mode === "chat"
      ? "Exploring the graph"
      : mode === "basic"
      ? "Getting started"
      : "Spinning up the agent swarm";
  const phaseLabel = maxLayer === 0 ? spinningUpLabel : PHASES[idx]?.label;

  // Gentle tick so the ETA text feels alive even between events.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (done) return;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [done]);

  return (
    <div className="glass rounded-2xl overflow-hidden">
      <div className="px-6 py-5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <span className="relative flex h-2.5 w-2.5 shrink-0">
              <span className="absolute inline-flex h-full w-full rounded-full bg-accent-glow opacity-70 animate-ping" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent-glow" />
            </span>
            <div className="min-w-0">
              <div className="text-[15px] font-semibold text-white truncate">
                {phaseLabel}
              </div>
              {lastMsg && (
                <div className="text-[12px] text-white/45 truncate mt-0.5">
                  {lastMsg}
                </div>
              )}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-[13px] font-mono text-accent-glow">
              {fmtEta(eta)}
            </div>
            <div className="text-[11px] text-white/35 font-mono">
              step {idx + 1}/{PHASES.length}
            </div>
          </div>
        </div>

        <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-white/8">
          <div
            className="h-full rounded-full bg-gradient-to-r from-accent to-accent-cyan transition-all duration-700 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>

        <button
          onClick={() => setShowDetails((v) => !v)}
          className="mt-4 inline-flex items-center gap-1.5 text-[12px] text-white/45 transition hover:text-white/80"
        >
          <span
            className={`inline-block transition-transform ${
              showDetails ? "rotate-90" : ""
            }`}
          >
            ▸
          </span>
          {showDetails ? "Hide agent details" : "Show agent details"}
        </button>
      </div>

      {showDetails && (
        <div className="border-t border-white/8 px-3 pb-3 pt-1 animate-fade-in">
          <AgentFeed events={events} done={done} connected={connected} />
        </div>
      )}
    </div>
  );
}
