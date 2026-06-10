import { useEffect, useState } from "react";
import { getComments, addComment, patchComment } from "../api";

// Lightweight, single-tenant collaboration: notes pinned to a report, optionally
// assigned to a teammate and resolvable. No auth — names are free-text, which is
// honest about this being a shared-workspace prototype rather than full multi-user.
export default function CommentsPanel({ reportId }) {
  const [comments, setComments] = useState([]);
  const [author, setAuthor] = useState(() => localStorage.getItem("df_author") || "");
  const [body, setBody] = useState("");
  const [assignedTo, setAssignedTo] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setComments(await getComments(reportId));
    } catch {
      /* non-fatal */
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId]);

  const submit = async () => {
    if (!body.trim() || busy) return;
    setBusy(true);
    try {
      if (author.trim()) localStorage.setItem("df_author", author.trim());
      await addComment(reportId, {
        author: author.trim() || "Anonymous",
        body: body.trim(),
        assignedTo: assignedTo.trim() || null,
      });
      setBody("");
      setAssignedTo("");
      await load();
    } finally {
      setBusy(false);
    }
  };

  const toggleResolved = async (c) => {
    await patchComment(c.id, { resolved: !c.resolved });
    await load();
  };

  return (
    <div className="space-y-4">
      {comments.length === 0 && (
        <p className="text-[13px] text-white/40">
          No notes yet. Leave a comment for your team or assign a follow-up.
        </p>
      )}

      <ul className="space-y-2.5">
        {comments.map((c) => (
          <li
            key={c.id}
            className={`rounded-xl border p-3 ${
              c.resolved
                ? "border-white/6 bg-white/[0.01] opacity-60"
                : "border-white/8 bg-white/[0.02]"
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-[11px]">
                  <span className="font-semibold text-white/75">{c.author}</span>
                  {c.assigned_to && (
                    <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-sky-200">
                      → {c.assigned_to}
                    </span>
                  )}
                  {c.resolved && (
                    <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-emerald-200">
                      resolved
                    </span>
                  )}
                </div>
                <p
                  className={`mt-1 text-[13px] leading-relaxed ${
                    c.resolved ? "text-white/45 line-through" : "text-white/80"
                  }`}
                >
                  {c.body}
                </p>
              </div>
              <button
                onClick={() => toggleResolved(c)}
                className="shrink-0 rounded-md border border-white/10 px-2 py-1 text-[10px] text-white/55 hover:bg-white/5"
              >
                {c.resolved ? "Reopen" : "Resolve"}
              </button>
            </div>
          </li>
        ))}
      </ul>

      <div className="space-y-2 rounded-xl border border-white/8 bg-white/[0.02] p-3">
        <div className="flex gap-2">
          <input
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            placeholder="Your name"
            className="w-1/2 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-[12.5px] text-white/85 placeholder:text-white/30 focus:border-accent-glow/50 focus:outline-none"
          />
          <input
            value={assignedTo}
            onChange={(e) => setAssignedTo(e.target.value)}
            placeholder="Assign to (optional)"
            className="w-1/2 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-[12.5px] text-white/85 placeholder:text-white/30 focus:border-accent-glow/50 focus:outline-none"
          />
        </div>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Add a note or follow-up for your team…"
          rows={2}
          className="w-full resize-none rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-[13px] text-white/85 placeholder:text-white/30 focus:border-accent-glow/50 focus:outline-none"
        />
        <button
          onClick={submit}
          disabled={busy || !body.trim()}
          className="rounded-lg border border-accent/40 bg-accent/15 px-3 py-1.5 text-[12.5px] font-medium text-accent-glow transition hover:bg-accent/25 disabled:opacity-40"
        >
          {busy ? "Posting…" : "Post note"}
        </button>
      </div>
    </div>
  );
}
