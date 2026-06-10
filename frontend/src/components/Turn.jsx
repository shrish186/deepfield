import { useCallback } from "react";
import { useWebSocket } from "../hooks/useWebSocket";
import RunningStatus from "./RunningStatus";
import ReportView from "./ReportView";

// A single query→report exchange in a thread. Reports loaded from history are
// already complete, so they render statically; a freshly launched report opens
// the live feed and swaps to the report when it finishes.
export default function Turn({ report, onDrillDown, onDone, onRetry }) {
  const alreadyDone = report.status === "completed" || report.status === "failed";
  const { events, done, connected } = useWebSocket(
    alreadyDone ? null : report.id
  );
  const finished = alreadyDone || done;

  // The WebSocket only signals "complete", not whether the run succeeded.
  // ReportView fetches the report and reports the real status back, so a failed
  // run unblocks the input and is recorded as "failed" (not "completed").
  const handleStatus = useCallback(
    (status) => {
      if (!alreadyDone) onDone?.(report.id, status);
    },
    [alreadyDone, report.id, onDone]
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-tr-sm border border-white/10 bg-white/[0.05] px-4 py-2.5 text-[14px] text-white/90">
          {report.query}
        </div>
      </div>

      {finished ? (
        <ReportView
          reportId={report.id}
          onDrillDown={onDrillDown}
          onRetry={onRetry}
          onStatus={handleStatus}
        />
      ) : (
        <RunningStatus
          events={events}
          done={done}
          connected={connected}
          mode={report.mode}
        />
      )}
    </div>
  );
}
