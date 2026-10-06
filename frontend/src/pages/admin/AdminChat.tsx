import { useEffect, useRef, useState } from 'react';
import { streamChat, type ChatEvent, type ChatTurn } from '../../services/chatStream';

/**
 * The officer assistant.
 *
 * Three things on this screen are requirements rather than decoration, each recorded
 * in Phase 4b's carried-forward section:
 *
 * 1. Tool calls appear as they happen, before their results. An officer watching
 *    "searching the policy corpus…" understands a twenty-second pause; a spinner does
 *    not. The backend emits tool_call before running the tool precisely so this is
 *    possible.
 * 2. A step-limit surrender must not look like an answer. The agent gives up with a
 *    sentence, and rendered as an ordinary bubble that sentence reads as a
 *    conclusion.
 * 3. Nothing here uses dangerouslySetInnerHTML. Tool arguments and results are
 *    model-generated and can carry text a member of the public wrote into a
 *    complaint; React escapes by default and that default is load-bearing.
 */

interface ToolActivity {
  name: string;
  args: Record<string, unknown>;
  result?: string;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
  tools?: ToolActivity[];
  hitStepLimit?: boolean;
  failed?: boolean;
}

const SUGGESTIONS = [
  'What work orders are at risk right now?',
  'What does the SOP say about who owns road surface defects?',
  'How is the department doing overall?',
  'Which contractor should take a WATER job, and why?',
];

/** A tool name as a person would say it, with the arguments that were used. */
function describeTool(tool: ToolActivity): string {
  const verbs: Record<string, string> = {
    search_policy: 'Searching the policy corpus',
    find_complaints: 'Looking up complaints',
    get_complaint: 'Reading a complaint',
    work_orders_at_risk: 'Checking SLA risk',
    contractor_options: 'Ranking contractors',
    tenant_statistics: 'Gathering statistics',
  };
  const base = verbs[tool.name] ?? tool.name;
  const args = Object.entries(tool.args)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(', ');
  return args ? `${base} (${args})` : base;
}

export default function AdminChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [liveTools, setLiveTools] = useState<ToolActivity[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, liveTools]);

  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setBusy(true);
    setInput('');
    setLiveTools([]);

    // Only the text is replayed as history. Tool activity belongs to the turn that
    // produced it and re-sending it would spend context on the model's own workings.
    const history: ChatTurn[] = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: 'user', content: question }]);

    const tools: ToolActivity[] = [];
    let answered = false;

    try {
      await streamChat(question, history, (event: ChatEvent) => {
        if (event.type === 'tool_call') {
          tools.push({ name: event.name, args: event.args });
          setLiveTools([...tools]);
        } else if (event.type === 'tool_result') {
          // Match by name to the most recent call of that name still awaiting one.
          for (let i = tools.length - 1; i >= 0; i -= 1) {
            if (tools[i].name === event.name && tools[i].result === undefined) {
              tools[i].result = event.result;
              break;
            }
          }
          setLiveTools([...tools]);
        } else if (event.type === 'answer') {
          answered = true;
          setMessages((prev) => [...prev, {
            role: 'assistant', content: event.text, tools: [...tools],
            hitStepLimit: Boolean(event.hit_step_limit),
          }]);
        } else if (event.type === 'error') {
          answered = true;
          setMessages((prev) => [...prev, {
            role: 'assistant', content: event.message, tools: [...tools], failed: true,
          }]);
        }
      });

      if (!answered) {
        // The stream closed with no terminal event. Saying so beats an empty bubble,
        // which is indistinguishable from a request still in flight.
        setMessages((prev) => [...prev, {
          role: 'assistant', failed: true, tools: [...tools],
          content: 'The assistant stopped responding before it answered.',
        }]);
      }
    } finally {
      // Whatever went wrong, the composer comes back. A screen that keeps its input
      // disabled after a failure cannot even be retried.
      setLiveTools([]);
      setBusy(false);
    }
  }

  return (
    <div className="max-w-4xl mx-auto flex flex-col" style={{ height: 'calc(100vh - 160px)' }}>
      <div className="mb-4">
        <h1 className="text-3xl font-bold text-gray-900">Assistant</h1>
        <p className="text-sm text-gray-500 mt-1">
          Answers come from your department&apos;s records and the municipal policy corpus.
          It can read; it cannot change anything.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 pr-1">
        {messages.length === 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
            <p className="text-sm text-gray-600 mb-3">Try one of these:</p>
            <div className="flex flex-col gap-2 items-start">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => ask(s)}
                        className="text-left text-sm text-blue-800 bg-blue-50 hover:bg-blue-100 rounded-lg px-3 py-2 transition">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message, index) => (
          <div key={index} className={message.role === 'user' ? 'flex justify-end' : ''}>
            {message.role === 'user' ? (
              <div className="bg-blue-900 text-white rounded-xl rounded-br-sm px-4 py-3 max-w-xl">
                {message.content}
              </div>
            ) : (
              <div className="max-w-3xl">
                {message.tools && message.tools.length > 0 && (
                  <ToolTrail tools={message.tools} />
                )}
                {/* A surrender and a failure are deliberately not the same shape as
                    an answer: amber for "I gave up", red for "it broke". */}
                <div className={
                  message.hitStepLimit
                    ? 'bg-amber-50 border border-amber-300 rounded-xl px-4 py-3'
                    : message.failed
                      ? 'bg-red-50 border border-red-300 rounded-xl px-4 py-3'
                      : 'bg-white border border-gray-200 rounded-xl px-4 py-3 shadow-sm'
                }>
                  {message.hitStepLimit && (
                    <p className="text-xs font-semibold text-amber-800 mb-1 uppercase tracking-wide">
                      Gave up — not an answer
                    </p>
                  )}
                  {message.failed && (
                    <p className="text-xs font-semibold text-red-800 mb-1 uppercase tracking-wide">
                      Failed
                    </p>
                  )}
                  <p className="text-gray-800 whitespace-pre-wrap">{message.content}</p>
                </div>
              </div>
            )}
          </div>
        ))}

        {busy && (
          <div className="max-w-3xl">
            <ToolTrail tools={liveTools} live />
            {liveTools.length === 0 && (
              <p className="text-sm text-gray-400 italic px-1">Thinking…</p>
            )}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => { e.preventDefault(); ask(input); }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={busy}
          placeholder="Ask about complaints, work orders, contractors or policy…"
          className="flex-1 border border-gray-300 rounded-lg px-4 py-3 outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="bg-blue-900 text-white rounded-lg px-6 py-3 font-medium disabled:opacity-40 hover:bg-blue-800 transition"
        >
          {busy ? 'Working…' : 'Ask'}
        </button>
      </form>
    </div>
  );
}

/** The tool calls behind an answer, in the order they were made. */
function ToolTrail({ tools, live = false }: { tools: ToolActivity[]; live?: boolean }) {
  if (tools.length === 0) return null;
  return (
    <div className="mb-2 space-y-1">
      {tools.map((tool, i) => (
        <div key={i} className="flex items-start gap-2 text-xs text-gray-500 px-1">
          <span className={tool.result === undefined && live
            ? 'text-blue-600 animate-pulse'
            : 'text-green-600'}>
            {tool.result === undefined && live ? '◌' : '✓'}
          </span>
          <span>{describeTool(tool)}</span>
        </div>
      ))}
    </div>
  );
}
