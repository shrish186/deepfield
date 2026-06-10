import { useEffect, useRef, useState } from "react";
import { WS_BASE } from "../api";

// Subscribes to the live agent feed for a report. Returns the accumulated
// events and a `done` flag set when the backend signals completion.
export function useWebSocket(reportId) {
  const [events, setEvents] = useState([]);
  const [done, setDone] = useState(false);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    if (!reportId) return;

    setEvents([]);
    setDone(false);

    const ws = new WebSocket(`${WS_BASE}/ws/reports/${reportId}`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (data.type === "complete") {
          setDone(true);
        } else if (data.type === "log") {
          setEvents((prev) => [...prev, data]);
        }
      } catch (e) {
        // ignore malformed frames
      }
    };

    return () => {
      ws.close();
    };
  }, [reportId]);

  return { events, done, connected };
}
