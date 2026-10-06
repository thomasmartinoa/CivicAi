import { API_BASE_URL } from './api';

/**
 * Live pipeline updates for one complaint.
 *
 * The backend has published a node update per graph step since Phase 1 and nothing
 * has ever listened. Until now the tracking screen inferred a progress bar from the
 * stored status, using v1 stage names — `validated`, `classified`, `routed` — that
 * the v2 graph never writes, so the bar sat at "Submitted" for the whole run and then
 * jumped to the end.
 */

export interface NodeUpdate {
  node: string;
  /** The decision the node logged, written for a citizen rather than an officer.
   *  Null when the node recorded no decision. */
  summary: string | null;
}

/** Open the socket. Returns a closer; the caller owns the lifetime. */
export function watchComplaint(
  trackingId: string,
  onUpdate: (update: NodeUpdate) => void,
): () => void {
  // ws:// from http://, wss:// from https://. Hardcoding either breaks one of the
  // two deployments and only one of them is the one you test on.
  const url = `${API_BASE_URL.replace(/^http/, 'ws')}/complaints/ws/${trackingId}`;

  let socket: WebSocket | null = null;
  let closed = false;

  try {
    socket = new WebSocket(url);
  } catch {
    // A complaint that already finished has nothing to stream, and a browser that
    // cannot open the socket must not break the page that renders its result.
    return () => undefined;
  }

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data && typeof data.node === 'string') {
        onUpdate({ node: data.node, summary: data.summary ?? null });
      }
    } catch {
      /* A malformed frame is dropped rather than thrown: the run is still going. */
    }
  };

  // No error handler that surfaces to the user. The socket is an enhancement — the
  // complaint's state is already on the page from the HTTP fetch, and a closed socket
  // means "nothing more is happening", which is indistinguishable from a finished run.
  socket.onerror = () => undefined;

  return () => {
    closed = true;
    if (socket && socket.readyState <= WebSocket.OPEN) socket.close();
    void closed;
  };
}
