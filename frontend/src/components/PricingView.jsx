import Logo from "./Logo";

const PLANS = [
  {
    id: "free",
    name: "Free",
    price: "$0",
    cadence: "forever",
    tagline: "For trying Deepfield out.",
    features: [
      "3 deep research runs / month",
      "Unlimited basic + chat answers",
      "Web & academic sources",
      "Disagreement graph (read-only)",
    ],
    cta: "Get started",
    highlight: false,
  },
  {
    id: "pro",
    name: "Pro",
    price: "$29",
    cadence: "per month",
    tagline: "For serious, daily research.",
    features: [
      "Everything in Free",
      "Unlimited deep reports",
      "PDF upload & paper compare",
      "Citation exports (APA/MLA/BibTeX)",
      "Priority pipeline queue",
    ],
    cta: "Subscribe to Pro",
    highlight: true,
  },
  {
    id: "team",
    name: "Team",
    price: "$99",
    cadence: "per month",
    tagline: "For labs and research groups.",
    features: [
      "Everything in Pro",
      "Shared threads & comments",
      "Assign findings to teammates",
      "5 seats included",
      "Centralized billing",
    ],
    cta: "Subscribe to Team",
    highlight: false,
  },
];

// Stripe-ready pricing page. We never collect card numbers ourselves — the
// Subscribe buttons will hand off to Stripe-hosted Checkout once wired up.
export default function PricingView({ user, onSelectPlan }) {
  return (
    <div className="mx-auto max-w-5xl px-5 py-14">
      <button
        onClick={() => (window.location.hash = "")}
        className="mb-10 flex items-center gap-2.5 transition hover:opacity-80"
      >
        <Logo size={30} />
        <span className="text-base font-bold tracking-tight text-white">Deepfield</span>
      </button>

      <div className="text-center">
        <h1 className="text-4xl font-extrabold tracking-tight">
          <span className="text-gradient">Research that compounds.</span>
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-[15px] leading-relaxed text-white/55">
          Start free. Upgrade when your research does. Every plan feeds the same
          growing map of scientific disagreement.
        </p>
      </div>

      <div className="mt-12 grid gap-5 md:grid-cols-3">
        {PLANS.map((plan) => {
          const current = user?.plan === plan.id;
          return (
            <div
              key={plan.id}
              className={`relative flex flex-col rounded-2xl border p-6 ${
                plan.highlight
                  ? "border-accent/50 bg-gradient-to-b from-accent/[0.08] to-white/[0.02] shadow-glow"
                  : "border-white/10 bg-white/[0.03]"
              }`}
            >
              {plan.highlight && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-gradient-to-r from-accent to-accent-cyan px-3 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white">
                  Most popular
                </span>
              )}
              <h3 className="text-lg font-bold text-white">{plan.name}</h3>
              <p className="mt-1 text-[13px] text-white/50">{plan.tagline}</p>
              <div className="mt-4 flex items-baseline gap-1.5">
                <span className="text-3xl font-extrabold text-white">{plan.price}</span>
                <span className="text-[13px] text-white/45">{plan.cadence}</span>
              </div>

              <ul className="mt-5 space-y-2.5">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-[13.5px] text-white/70">
                    <svg
                      className="mt-0.5 shrink-0 text-accent-cyan"
                      width="15"
                      height="15"
                      viewBox="0 0 24 24"
                      fill="none"
                    >
                      <path
                        d="M20 6 9 17l-5-5"
                        stroke="currentColor"
                        strokeWidth="2.4"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    {f}
                  </li>
                ))}
              </ul>

              <button
                disabled={current}
                onClick={() => onSelectPlan?.(plan)}
                className={`mt-6 w-full rounded-xl px-4 py-2.5 text-sm font-semibold transition ${
                  current
                    ? "cursor-default border border-white/10 bg-white/5 text-white/50"
                    : plan.highlight
                    ? "bg-gradient-to-r from-accent to-accent-cyan text-white shadow-glow hover:brightness-110"
                    : "border border-white/15 bg-white/5 text-white hover:bg-white/10"
                }`}
              >
                {current ? "Current plan" : plan.cta}
              </button>
            </div>
          );
        })}
      </div>

      <p className="mt-10 text-center text-[12.5px] text-white/35">
        Payments are processed securely by Stripe. We never see or store your card details.
      </p>
      <div className="mt-6 text-center">
        <button
          onClick={() => (window.location.hash = "")}
          className="text-[13px] text-white/40 transition hover:text-white/70"
        >
          ← Back to research
        </button>
      </div>
    </div>
  );
}
