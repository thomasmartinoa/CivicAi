import { useQuery } from '@tanstack/react-query';
import { getEvals } from '../../services/api';
import type { EvalDashboard, EvalMetric, EvalRunRow } from '../../types';

/**
 * How well the system actually classifies, and whether retrieval earns its place.
 *
 * The three configurations are the Phase 3 comparison: `keyword` is no model at all,
 * `llm_only` is the model without retrieval, `full` is the model with it. The gap
 * between the last two is the only evidence that the whole RAG apparatus is worth
 * running.
 *
 * The loudest thing on this screen is the stale-baseline warning, because a baseline
 * measured under a different validator describes a different population reaching
 * `classify` — a regression against it may be a population change rather than a model
 * one, and a dashboard that does not say so is worse than one with no baseline.
 */

const CONFIG_LABELS: Record<string, string> = {
  keyword: 'Keyword baseline',
  llm_only: 'Model, no retrieval',
  full: 'Model with retrieval',
};

const CONFIG_ORDER = ['keyword', 'llm_only', 'full'];

export default function AdminEvals() {
  const { data, isLoading, isError } = useQuery<EvalDashboard>({
    queryKey: ['evals'],
    queryFn: async () => (await getEvals()).data,
  });

  if (isLoading) return <p className="text-center text-gray-500 py-20">Loading…</p>;
  if (isError || !data) {
    return <p className="text-center text-red-600 py-20">Failed to load eval data.</p>;
  }

  const configs = CONFIG_ORDER.filter((c) => c in data.latest_by_config);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Evaluation</h1>
        <p className="text-sm text-gray-500 mt-1">
          Measured against a fixed golden set. These numbers are about the model, not
          about any one department.
        </p>
      </div>

      {data.baseline?.stale && (
        <div className="bg-amber-50 border border-amber-300 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-amber-900 uppercase tracking-wide">
            The baseline is stale
          </h2>
          <p className="text-sm text-amber-900 mt-2">
            It was measured with validator{' '}
            <span className="font-mono">{data.baseline.validate_version}</span>, and the
            pipeline now runs a different one. A different validator admits a different
            set of complaints to the classifier, so a change against this figure may be
            a population change rather than a model change. Re-run the sweep before
            trusting a comparison.
          </p>
        </div>
      )}

      {/* The three-column comparison. */}
      {configs.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {configs.map((config) => {
            const value = data.latest_by_config[config];
            return (
              <div key={config} className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                <p className="text-sm text-gray-500 mb-1">{CONFIG_LABELS[config] ?? config}</p>
                {/* Null means the newest run of this configuration reported no
                    macro-F1, which is not the same as scoring zero. */}
                <p className={value == null ? 'text-xl font-semibold text-gray-400'
                                            : 'text-3xl font-bold text-blue-900'}>
                  {value == null ? 'not measured' : value.toFixed(2)}
                </p>
                <p className="text-xs text-gray-400 mt-1">macro-F1</p>
              </div>
            );
          })}
        </div>
      )}

      {data.baseline && (
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <div className="flex items-baseline gap-3">
            <h2 className="text-lg font-semibold text-gray-800">Regression baseline</h2>
            <span className="text-2xl font-bold text-blue-900">
              {data.baseline.macro_f1?.toFixed(2) ?? '—'}
            </span>
            {data.baseline.validate_version && (
              <span className="text-xs text-gray-500">
                validator {data.baseline.validate_version}
              </span>
            )}
          </div>
          {data.baseline.note && (
            <p className="text-xs text-gray-500 mt-2 whitespace-pre-wrap">{data.baseline.note}</p>
          )}
        </div>
      )}

      <div>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Runs</h2>
        {data.runs.length === 0 ? (
          <p className="text-center text-gray-500 py-10 bg-white rounded-xl border border-gray-200">
            No eval runs recorded. Run{' '}
            <span className="font-mono text-xs">python -m app.evals.run --config all</span>.
          </p>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm divide-y divide-gray-100">
            {data.runs.map((run: EvalRunRow) => (
              <div key={run.id} className="px-5 py-4">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="text-xs font-semibold px-2 py-1 rounded bg-blue-100 text-blue-800">
                    {CONFIG_LABELS[run.config_label ?? ''] ?? run.config_label ?? 'unknown'}
                  </span>
                  <span className="text-sm text-gray-700">{run.dataset_name}</span>
                  {run.git_sha && (
                    <span className="font-mono text-xs text-gray-400">
                      {run.git_sha.slice(0, 7)}
                    </span>
                  )}
                  <span className="ml-auto text-xs text-gray-400">
                    {new Date(run.started_at).toLocaleString()}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
                  {run.metrics.length === 0 ? (
                    <span className="text-xs text-gray-400 italic">
                      No metrics recorded — this sweep did not finish.
                    </span>
                  ) : (
                    run.metrics.map((metric: EvalMetric) => (
                      <span key={metric.metric} className="text-xs text-gray-600">
                        <span className="text-gray-400">{metric.metric}</span>{' '}
                        <span className="font-semibold text-gray-900">
                          {metric.value.toFixed(3)}
                        </span>
                        {typeof metric.detail?.n === 'number' && (
                          <span className="text-gray-400"> (n={String(metric.detail.n)})</span>
                        )}
                      </span>
                    ))
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
