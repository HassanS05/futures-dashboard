"use client";

import { useEffect, useRef, useState } from "react";
import type { Quote } from "./types";

interface StreamPayload {
  type: string;
  quotes?: Quote[];
  portfolio?: {
    total_value: number;
    total_pnl: number;
    total_pnl_percent: number;
    day_pnl: number;
    day_pnl_percent: number;
  };
}

/**
 * Realtime hook backed by the FastAPI WebSocket. Auto-reconnects with backoff
 * and re-subscribes to the requested symbols. Falls back silently if the
 * socket is unavailable (UI still renders from REST snapshots).
 */
export function useStream(symbols: string[]) {
  const [data, setData] = useState<StreamPayload | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const symbolsKey = symbols.join(",");

  useEffect(() => {
    let retry = 0;
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;

    const connect = () => {
      const url =
        process.env.NEXT_PUBLIC_WS_URL ||
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/stream`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        retry = 0;
        ws.send(JSON.stringify({ symbols: symbolsKey.split(",").filter(Boolean) }));
      };
      ws.onmessage = (e) => setData(JSON.parse(e.data));
      ws.onclose = () => {
        setConnected(false);
        if (!closed) {
          retry = Math.min(retry + 1, 5);
          timer = setTimeout(connect, retry * 1500);
        }
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      wsRef.current?.close();
    };
  }, [symbolsKey]);

  return { data, connected };
}
