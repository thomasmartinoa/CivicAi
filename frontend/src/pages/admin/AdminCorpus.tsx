import { useQuery } from '@tanstack/react-query';
import { getCorpus } from '../../services/api';
import type { CorpusDocument, CorpusStatus } from '../../types';

/**
 * The knowledge base behind every grounded decision.
 *
 * Read-only, deliberately. A reindex button belongs to the same argument that kept
 * mutation tools out of the officer agent: rebuilding the index is destructive to the
 * thing every citation depends on, and this codebase has no confirmation mechanism.
 * The command is shown instead, so whoever needs it can run it knowingly.
 */
export default function AdminCorpus() {
  const { data, isLoading, isError } = useQuery<CorpusStatus>({
    queryKey: ['corpus'],
    queryFn: async () => (await getCorpus()).data,
  });

  if (isLoading) return <p className="text-center text-gray-500 py-20">Loading…</p>;
  if (isError || !data) {
    return <p className="text-center text-red-600 py-20">Failed to load the corpus status.</p>;
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Knowledge base</h1>
        <p className="text-sm text-gray-500 mt-1">
          The municipal documents the pipeline and the assistant cite. Every grounded
          decision points back into this corpus.
        </p>
      </div>

      {/* The missing-index case is the one worth designing for: the pipeline keeps
          running without an index and silently stops citing anything. */}
      {!data.available ? (
        <div className="bg-amber-50 border border-amber-300 rounded-xl p-6">
          <h2 className="text-lg font-semibold text-amber-900">No index is loaded</h2>
          <p className="text-sm text-amber-900 mt-2">{data.error}</p>
          <p className="text-sm text-amber-900 mt-3">
            Complaints will still be processed. They will be classified, scored and
            routed on the model&apos;s own judgement, and the decisions will carry no
            citations.
          </p>
          <pre className="mt-3 bg-amber-100 rounded-lg px-3 py-2 text-xs text-amber-900 overflow-x-auto">
            python -m app.ai.rag.ingest --collection all
          </pre>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat label="Documents" value={String(data.document_count)} />
            <Stat label="Chunks" value={String(data.chunk_count)} />
            <Stat label="Embedding model" value={data.embedding_model ?? 'not recorded'}
                  small />
            <Stat
              label="Built"
              small
              value={data.built_at ? new Date(data.built_at).toLocaleString() : 'unknown'}
            />
          </div>

          <div className="bg-white rounded-xl border border-gray-200 shadow-sm divide-y divide-gray-100">
            {data.documents.map((doc: CorpusDocument) => (
              <div key={doc.source} className="px-5 py-4">
                <div className="flex items-baseline gap-3 flex-wrap">
                  <span className="font-mono text-sm text-gray-900">{doc.source}</span>
                  {doc.title && <span className="text-sm text-gray-600">{doc.title}</span>}
                  <span className="ml-auto text-xs text-gray-400">
                    {doc.chunks} {doc.chunks === 1 ? 'chunk' : 'chunks'} ·{' '}
                    {(doc.characters / 1000).toFixed(1)}k characters
                  </span>
                </div>
                {doc.sections.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {doc.sections.map((section) => (
                      <span key={section}
                            className="text-xs bg-gray-100 text-gray-600 rounded px-2 py-0.5">
                        {section}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          <p className="text-xs text-gray-400">
            Index at <span className="font-mono">{data.index_dir}</span>. Rebuilding is
            a command-line operation on purpose — it replaces the index every citation
            depends on.
          </p>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, small = false }: { label: string; value: string; small?: boolean }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
      <p className="text-sm text-gray-500 mb-1">{label}</p>
      <p className={small ? 'text-sm font-semibold text-gray-900 break-all'
                          : 'text-3xl font-bold text-blue-900'}>{value}</p>
    </div>
  );
}
