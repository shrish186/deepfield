import { useEffect, useRef } from "react";

const LAYER_META = {
  0: { tag: "SYS", dot: "bg-white/40", text: "text-white/50" },
  1: { tag: "L1", dot: "bg-cyan-400", text: "text-cyan-300" },
  2: { tag: "L2", dot: "bg-emerald-400", text: "text-emerald-300" },
  3: { tag: "L3", dot: "bg-violet-400", text: "text-violet-300" },
  4: { tag: "L4", dot: "bg-amber-400", text: "text-amber-300" },
  5: { tag: "L5", dot: "bg-accent-glow", text: "text-accent-glow" },
};

export default function AgentFeed({ events, done, connected }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  const streaming = !done && connected;

  return (
    <div
      className={`glass rounded-2xl overflow-hidden ${
        streaming ? "gradient-ring" : ""
      }`}
    >
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/8">
        <div className="flex items-center gap-2">
          <h2 className="text-[13px] font-semibold tracking-tight text-white">
            Live Agent Feed
          </h2>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              done ? "bg-white/30" : connected ? "bg-emerald-400 animate-pulse" : "bg-rose-500"
            }`}
          />
          <span className="text-white/45 font-mono">
            {done ? "complete" : connected ? "streaming" : "connecting"}
          </span>
        </div>
      </div>

      <div className="max-h-[440px] overflow-y-auto px-4 py-3 font-mono text-[12px] leading-relaxed">
        {events.length === 0 && (
          <div className="text-white/35 px-1 py-2">Spinning up agents…</div>
        )}
        {events.map((ev, i) => {
          const meta = LAYER_META[ev.layer] || LAYER_META[0];
          return (
            <div
              key={i}
              className="flex gap-3 items-start rounded-lg px-2 py-1 animate-fade-up hover:bg-white/[0.03]"
            >
              <span className="flex items-center gap-1.5 shrink-0 pt-0.5">
                <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
                <span className={`${meta.text} w-6`}>{meta.tag}</span>
              </span>
              <span className="text-white/80 break-words">{ev.message}</span>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
    </div>
  );
}
