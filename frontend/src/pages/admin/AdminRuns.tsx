import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getRunDetail, getRuns } from '../../services/api';
import type { AgentRun, AgentRunDetail, AgentStep } from '../../types';

/**
 * The agent trace viewer.
 *
 * Every pipeline run has written a step timeline since Phase 1 and every chat turn
 * has written one since Phase 4b, and until now none of it could be seen. This is
 * the screen that makes a decision auditable: which nodes ran, how long each took,
 * what went in and what came out.
 *
 * Two things here are requirements rather than styling. A `step_limit` status is an
 * agent that gave up and must not look like one that finished. And a failed run must
 * be visible in the list without opening it, because the reason to come here is
 * usually that something went wrong.
 */

const STATUS_STYLE: Record<string, string> = {
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  step_limit: 'bg-amber-100 text-amber-900',
  running: 'bg-blue-100 text-blue-800',
};

function statusChip(status: string) {
  return STATUS_STYLE[status] ?? 'bg-gray-100 text-gray-700';
}

/** `step_limit` is not a word an officer should have to decode. */
function statusLabel(status: string) {
  return status === 'step_limit' ? 'gave up' : status;
}

function duration(ms: number | null): string {
  if (ms === null || ms === undefined) return '—';
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export default function AdminRuns() {
  const [kind, setKind] = useState<string>('');
  const [openId, setOpenId] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery<{ items: AgentRun[]; total: number }>({
    queryKey: ['runs', kind],
    queryFn: async () => (await getRuns(kind ? { kind } : undefined)).data,
    refetchInterval: 15000,
  });

  if (isError) {
    return <p className="text-center text-red-600 py-20">Failed to load agent runs.</p>;
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Agent traces</h1>
        <p className="text-sm text-gray-500 mt-1">
          Every pipeline run and every assistant conversation, with the steps behind it.
        </p>
      </div>

      <div className="flex gap-2">
        {[
          { value: '', label: 'All' },
          { value: 'pipeline', label: 'Pipeline runs' },
          { value: 'chat', label: 'My conversations' },
        ].map((option) => (
          <button
            key={option.value}
            onClick={() => { setKind(option.value); setOpenId(null); }}
            className={
              kind === option.value
                ? 'px-4 py-2 rounded-lg text-sm font-semibold bg-blue-900 text-white'
                : 'px-4 py-2 rounded-lg text-sm font-medium bg-white border border-gray-300 text-gray-700 hover:bg-gray-50'
            }
          >
            {option.label}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-gray-500 py-8 text-center">Loading…</p>}

      {!isLoading && data && data.items.length === 0 && (
        <p className="text-center text-gray-500 py-12 bg-white rounded-xl border border-gray-200">
          No runs yet. Submit a complaint or ask the assistant something.
        </p>
      )}

      <div className="space-y-3">
        {data?.items.map((run) => (
          <div key={run.id} className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <button
              onClick={() => setOpenId(openId === run.id ? null : run.id)}
              className="w-full text-left px-5 py-4 flex items-center gap-4 hover:bg-gray-50 rounded-xl transition"
            >
              <span className={`text-xs font-semibold px-2 py-1 rounded-lg ${statusChip(run.status)}`}>
                {statusLabel(run.status)}
              </span>
              <span className="text-xs font-medium px-2 py-1 rounded-lg bg-gray-100 text-gray-700">
                {run.kind}
              </span>
              <span className={run.tracking_id
                ? 'font-mono text-sm text-gray-800'
                : 'text-sm text-gray-800 truncate max-w-md'}>
                {run.label ?? (run.tracking_id ?? 'conversation')}
              </span>
              <span className="text-xs text-gray-500">
                {run.step_count} {run.step_count === 1 ? 'step' : 'steps'}
              </span>
              <span className="text-xs text-gray-500">{duration(run.duration_ms)}</span>
              <span className="ml-auto text-xs text-gray-400">
                {new Date(run.started_at).toLocaleString()}
              </span>
              <span className="text-gray-400">{openId === run.id ? '▾' : '▸'}</span>
            </button>

            {/* The error belongs in the list, not only behind a click: the usual
                reason to open this screen is that something went wrong. */}
            {run.error && (
              <p className="px-5 pb-3 -mt-1 text-xs text-red-700 font-mono break-all">
                {run.error.slice(0, 300)}
              </p>
            )}

            {openId === run.id && <RunTimeline runId={run.id} />}
          </div>
        ))}
      </div>
    </div>
  );
}

function RunTimeline({ runId }: { runId: string }) {
  const { data, isLoading } = useQuery<AgentRunDetail>({
    queryKey: ['run', runId],
    queryFn: async () => (await getRunDetail(runId)).data,
  });

  if (isLoading) return <p className="px-5 pb-4 text-sm text-gray-400">Loading steps…</p>;
  if (!data) return null;

  return (
    <div className="border-t border-gray-100 px-5 py-4 space-y-3">
      {data.steps.length === 0 && (
        <p className="text-sm text-gray-500">This run recorded no steps.</p>
      )}
      {data.steps.map((step: AgentStep) => (
        <div key={step.seq} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span className={`w-6 h-6 rounded-full text-xs flex items-center justify-center font-semibold ${statusChip(step.status)}`}>
              {step.seq}
            </span>
            <span className="flex-1 w-px bg-gray-200 my-1" />
          </div>
          <div className="flex-1 pb-2 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-gray-900 text-sm">{step.node}</span>
              {step.status !== 'completed' && (
                <span className={`text-xs px-2 py-0.5 rounded ${statusChip(step.status)}`}>
                  {statusLabel(step.status)}
                </span>
              )}
              <span className="text-xs text-gray-400">{duration(step.duration_ms)}</span>
              {step.tokens !== null && (
                <span className="text-xs text-gray-400">{step.tokens} tokens</span>
              )}
            </div>
            {step.input_summary && (
              <Summary label="in" text={step.input_summary} />
            )}
            {step.output_summary && (
              <Summary label="out" text={step.output_summary} />
            )}
            {step.error && (
              <p className="mt-1 text-xs text-red-700 font-mono break-all">{step.error}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/** A step summary, which may be a 2000-character truncated tool result. */
function Summary({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 200;
  return (
    <div className="mt-1">
      <span className="text-[10px] uppercase tracking-wide text-gray-400 mr-2">{label}</span>
      <span className="text-xs text-gray-600 font-mono break-all whitespace-pre-wrap">
        {open || !long ? text : `${text.slice(0, 200)}…`}
      </span>
      {long && (
        <button onClick={() => setOpen(!open)}
                className="ml-2 text-xs text-blue-700 hover:underline">
          {open ? 'less' : 'more'}
        </button>
      )}
    </div>
  );
}
