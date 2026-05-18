import { useCallback, useEffect, useRef, useState } from "react";

import { ResilientWebSocket, type ResilientWebSocketStatus } from "./resilientWebSocket";

export function useResilientWebSocket(
  url: string | null,
  onTextMessage: (text: string) => void,
): {
  status: ResilientWebSocketStatus;
  statusDetail: string | null;
  reconnectNow: () => void;
} {
  const [status, setStatus] = useState<ResilientWebSocketStatus>("idle");
  const [statusDetail, setStatusDetail] = useState<string | null>(null);
  const clientRef = useRef<ResilientWebSocket | null>(null);
  const onMessageRef = useRef(onTextMessage);

  useEffect(() => {
    onMessageRef.current = onTextMessage;
  }, [onTextMessage]);

  const reconnectNow = useCallback(() => {
    clientRef.current?.disconnect();
    if (!url) {
      setStatus("idle");
      setStatusDetail(null);
      return;
    }
    const client = new ResilientWebSocket(url, {
      onTextMessage: (t) => onMessageRef.current(t),
      onStatus: (s, d) => {
        setStatus(s);
        setStatusDetail(d ?? null);
      },
    });
    clientRef.current = client;
    client.connect();
  }, [url]);

  useEffect(() => {
    reconnectNow();
    return () => {
      clientRef.current?.disconnect();
      clientRef.current = null;
    };
  }, [reconnectNow]);

  return { status, statusDetail, reconnectNow };
}
