import { useState } from "react";
import { getByokKeys, saveByokKeys } from "../api";

// Bring-your-own-key panel. Keys live only in this browser (localStorage) and
// ride along as request headers so runs bill the user, not the server — which
// also lifts the shared usage caps. Nothing here is ever stored server-side.
export default function KeySettings({ onClose, onSaved }) {
  const existing = getByokKeys();
  const [anthropic, setAnthropic] = useState(existing.anthropic || "");
  const [tavily, setTavily] = useState(existing.tavily || "");
  const [voyage, setVoyage] = useState(existing.voyage || "");

  const save = () => {
    saveByokKeys({ anthropic, tavily, voyage });
    onSaved?.();
    onClose?.();
  };

  const clear = () => {
    saveByokKeys({});
    setAnthropic("");
    setTavily("");
    setVoyage("");
    onSaved?.();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-5 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-white/10 bg-ink-900/95 p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-white">Use your own API keys</h2>
        <p className="mt-1.5 text-[13px] leading-relaxed text-white/55">
          Bring your own keys to run unlimited research — usage bills your account
          directly and skips the shared daily caps. Keys are stored only in this
          browser and sent with your requests; they are never saved on the server.
        </p>

        <div className="mt-5 space-y-3.5">
          <Field
            label="Anthropic API key"
            hint="Required · console.anthropic.com"
            value={anthropic}
            onChange={setAnthropic}
            placeholder="sk-ant-..."
          />
          <Field
            label="Tavily API key"
            hint="Required · app.tavily.com"
            value={tavily}
            onChange={setTavily}
            placeholder="tvly-..."
          />
          <Field
            label="Voyage API key"
            hint="Optional · enables the disagreement graph"
            value={voyage}
            onChange={setVoyage}
            placeholder="pa-..."
          />
        </div>

        <div className="mt-6 flex items-center justify-between gap-3">
          <button
            onClick={clear}
            className="text-[13px] text-white/45 transition hover:text-white/70"
          >
            Clear keys
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded-xl border border-white/15 px-4 py-2 text-sm text-white/80 transition hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              onClick={save}
              className="rounded-xl bg-gradient-to-r from-accent to-accent-cyan px-4 py-2 text-sm font-semibold text-white shadow-glow transition hover:brightness-110"
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, value, onChange, placeholder }) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline justify-between">
        <span className="text-[12.5px] font-medium text-white/70">{label}</span>
        <span className="text-[11px] text-white/35">{hint}</span>
      </span>
      <input
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2.5 text-sm text-white placeholder:text-white/30 focus:border-accent-glow/60 focus:outline-none focus:ring-1 focus:ring-accent-glow/30"
      />
    </label>
  );
}
