import { API_BASE_URL } from './api';

/**
 * The officer chat SSE client.
 *
 * Not EventSource: that is GET-only and cannot set an Authorization header, and this
 * endpoint is an authenticated POST carrying a question and the conversation history.
 * So it is `fetch` plus a stream reader, which also means the frame parsing is ours.
 *
 * The buffering matters. A chunk boundary falls wherever the network puts it, not on
 * a frame boundary, so a naive `split('\n\n')` on each chunk drops the half-frame at
 * the end of one read and the half at the start of the next. The remainder is carried
 * across reads.
 */

export type ChatEvent =
  | { type: 'tool_call'; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; name: string; result: string }
  | { type: 'answer'; text: string; hit_step_limit?: boolean }
  | { type: 'error'; message: string }
  | { type: 'done' };

export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

/** Parse one `event:`/`data:` block. Returns null for a blank or malformed block. */
function parseFrame(block: string): ChatEvent | null {
  let name = '';
  let data = '';
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) name = line.slice(7).trim();
    else if (line.startsWith('data: ')) data = line.slice(6);
  }
  if (!name) return null;
  try {
    return { type: name, ...(data ? JSON.parse(data) : {}) } as ChatEvent;
  } catch {
    // A frame we cannot parse is dropped rather than thrown: one bad frame must not
    // end a turn that is still producing good ones.
    return null;
  }
}

export async function streamChat(
  question: string,
  history: ChatTurn[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem('admin_token');

  // Inside the try, not before it. A fetch that rejects outright — the backend is
  // down, or CORS refused the preflight — used to throw out of this function with
  // nothing catching it, so the screen sat on "Thinking…" for ever with no error and
  // no way back. Found by rendering the page and watching it hang.
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/admin/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ question, history }),
      signal,
    });
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') return;
    onEvent({
      type: 'error',
      message: 'Could not reach the assistant. Check that the API is running.',
    });
    onEvent({ type: 'done' });
    return;
  }

  if (!response.ok) {
    // Everything knowable before the stream opens arrives as an ordinary status: no
    // token, wrong role, a question the server rejected.
    const detail = await response.text().catch(() => '');
    onEvent({
      type: 'error',
      message:
        response.status === 401 || response.status === 403
          ? 'Your session has expired. Sign in again.'
          : `The assistant refused the request (${response.status}). ${detail.slice(0, 200)}`,
    });
    onEvent({ type: 'done' });
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    onEvent({ type: 'error', message: 'This browser cannot read the response stream.' });
    onEvent({ type: 'done' });
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() ?? '';   // the trailing partial frame, kept for next read
      for (const block of blocks) {
        const event = parseFrame(block);
        if (event) onEvent(event);
      }
    }
    const last = parseFrame(buffer);
    if (last) onEvent(last);
  } catch (err) {
    if ((err as Error)?.name !== 'AbortError') {
      onEvent({ type: 'error', message: 'The connection to the assistant was lost.' });
      onEvent({ type: 'done' });
    }
  }
}
