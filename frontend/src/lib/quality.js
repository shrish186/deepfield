// Plain-language quality bands.
//
// The graph stores everything as 0–1 scores, but a raw "0.98 / 0.30" tells a
// reader nothing. These helpers translate the underlying numbers into the few
// dimensions people actually reason about, kept deliberately distinct:
//
//   • Credibility  — how trustworthy a *source* is (its domain quality).
//   • Evidence     — how much independent support a *claim* has (source count).
//   • Agreement    — whether other reports *contest* the claim.
//
// We intentionally do NOT surface "confidence" as its own number: in this system
// confidence is just a function of the source count, so showing both a percentage
// and a source count side by side is redundant and reads as two signals when it's
// one. Evidence strength carries that meaning in words instead.

export function credibilityBand(score) {
  const s = score ?? 0;
  if (s >= 0.9)
    return { label: "Very high", cls: "text-emerald-300 bg-emerald-500/10 border-emerald-500/25" };
  if (s >= 0.75)
    return { label: "High", cls: "text-lime-300 bg-lime-500/10 border-lime-500/25" };
  if (s >= 0.5)
    return { label: "Moderate", cls: "text-amber-300 bg-amber-500/10 border-amber-500/25" };
  if (s >= 0.3)
    return { label: "Low", cls: "text-orange-300 bg-orange-500/10 border-orange-500/25" };
  return { label: "Unverified", cls: "text-rose-300 bg-rose-500/10 border-rose-500/25" };
}

// Evidence strength from the number of distinct sources backing a claim.
export function evidenceBand(supportCount) {
  const n = supportCount ?? 0;
  if (n >= 5) return { label: "Strong evidence", cls: "text-emerald-200" };
  if (n >= 3) return { label: "Moderate evidence", cls: "text-lime-200" };
  if (n === 2) return { label: "Limited evidence", cls: "text-amber-200" };
  if (n === 1) return { label: "Single source", cls: "text-orange-200" };
  return { label: "Unsupported", cls: "text-white/40" };
}

// Whether the claim is contested by other reports in the graph.
export function agreementBand(contested) {
  return contested
    ? { label: "Contested", cls: "text-amber-200" }
    : { label: "Uncontested", cls: "text-emerald-200/70" };
}

// Source-type → a human label + colour. Peer-reviewed scholarly types read green;
// preprints amber (not yet reviewed); news/web neutral; user uploads violet.
export function sourceTypeBadge(type) {
  switch (type) {
    case "journal":
      return { label: "Journal", cls: "text-emerald-300 bg-emerald-500/10 border-emerald-500/25" };
    case "medical":
      return { label: "Medical", cls: "text-teal-300 bg-teal-500/10 border-teal-500/25" };
    case "preprint":
      return { label: "Preprint", cls: "text-amber-300 bg-amber-500/10 border-amber-500/25" };
    case "news":
      return { label: "News", cls: "text-sky-300 bg-sky-500/10 border-sky-500/25" };
    case "uploaded":
      return { label: "Your upload", cls: "text-violet-300 bg-violet-500/10 border-violet-500/25" };
    default:
      return { label: "Web", cls: "text-white/55 bg-white/5 border-white/15" };
  }
}
