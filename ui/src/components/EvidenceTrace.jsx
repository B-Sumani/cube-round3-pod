import React, { useState } from 'react'
import VerdictBadge from './VerdictBadge'
import { truncateHash, formatTimestamp } from '../lib/format'
import { Hash, ArrowUpRight, FileCode, CheckCircle2, ShieldAlert, History, ChevronRight, Copy, Check } from 'lucide-react'

/**
 * Evidence Trace component rendered within the Charcoal band.
 * Displays:
 * - record_id
 * - upstream_refs
 * - content_hash
 * - inputs with sha256
 * - payload
 * - workflow transitions audit trail
 */
export default function EvidenceTrace({ workflow, evidence = {}, className = '' }) {
  const [selectedRecordId, setSelectedRecordId] = useState(null)
  const [copiedHash, setCopiedHash] = useState(null)

  const recordIds = workflow?.evidence_references || Object.keys(evidence)
  const activeRecordId = selectedRecordId || recordIds[0]
  const currentRecord = activeRecordId ? evidence[activeRecordId] : null
  const transitions = workflow?.transitions || []

  const handleCopy = (text, key) => {
    navigator.clipboard?.writeText(text)
    setCopiedHash(key)
    setTimeout(() => setCopiedHash(null), 2000)
  }

  if (recordIds.length === 0 && transitions.length === 0) {
    return (
      <div className="p-8 text-center text-[#D1CBBF] border-2 border-dashed border-[#5E5A52] rounded-card">
        No evidence records or audit transitions available yet.
      </div>
    )
  }

  return (
    <div className={`space-y-8 ${className}`}>
      {/* Evidence Records Section */}
      {recordIds.length > 0 && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-serif text-xl md:text-2xl text-cream font-bold flex items-center gap-2">
              <Hash size={20} className="text-mustard" />
              <span>Immutable Evidence Chain</span>
            </h3>
            <span className="text-xs text-[#D1CBBF]">
              {recordIds.length} recorded record(s)
            </span>
          </div>

          {/* Record Selector Tabs */}
          <div className="flex flex-wrap gap-2">
            {recordIds.map(rid => {
              const rec = evidence[rid]
              const isSelected = rid === activeRecordId
              const stage = rec?.stage || rid.split('-')[0]
              const verdict = rec?.decision?.verdict

              return (
                <button
                  key={rid}
                  type="button"
                  onClick={() => setSelectedRecordId(rid)}
                  className={`px-3.5 py-2 rounded-xl border-2 font-mono text-xs flex items-center gap-2 transition-all ${
                    isSelected
                      ? 'border-mustard bg-peach text-ink shadow-[3px_3px_0_var(--cream)] font-bold'
                      : 'border-[#5E5A52] bg-[#2E2E2E] text-cream hover:bg-[#3E3E3E]'
                  }`}
                  aria-pressed={isSelected}
                >
                  <span className="capitalize">{stage}:</span>
                  <span>{rid}</span>
                  {verdict && <VerdictBadge verdict={verdict} size="sm" />}
                </button>
              )
            })}
          </div>

          {/* Current Evidence Record Card (Peach / Cream on Charcoal) */}
          {currentRecord ? (
            <div className="border-2 border-ink rounded-card bg-card text-ink shadow-[4px_4px_0_#FFF6DE] p-5 md:p-6 space-y-6">
              {/* Record Metadata Header */}
              <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b-2 border-ink">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs uppercase font-bold tracking-wider text-muted">
                      Stage: <strong className="text-ink uppercase">{currentRecord.stage}</strong>
                    </span>
                    <span className="font-mono text-xs px-2 py-0.5 rounded bg-mustard/40 font-bold border border-ink">
                      {currentRecord.record_id}
                    </span>
                  </div>
                  <div className="text-xs text-muted font-mono">
                    Produced by: <strong className="text-ink">{currentRecord.agent_id}</strong>
                    {currentRecord.produced_at && ` • ${formatTimestamp(currentRecord.produced_at)}`}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <VerdictBadge verdict={currentRecord.decision?.verdict} size="md" />
                </div>
              </div>

              {/* Content Hash & Upstream Refs */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Content Hash */}
                <div className="p-3.5 rounded-xl border-2 border-ink bg-[#FFFDF6]">
                  <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider text-muted mb-1">
                    <span>Cryptographic Content Hash</span>
                    <button
                      type="button"
                      onClick={() => handleCopy(currentRecord.content_hash, 'hash')}
                      className="p-1 text-ink hover:text-mustard flex items-center gap-1 font-mono text-[11px]"
                      aria-label="Copy SHA256 content hash"
                    >
                      {copiedHash === 'hash' ? <Check size={12} className="text-[#2E9E6B]" /> : <Copy size={12} />}
                      {copiedHash === 'hash' ? 'Copied' : 'Copy'}
                    </button>
                  </div>
                  <div className="font-mono text-xs text-ink font-semibold break-all bg-stone-100 p-2 rounded-lg border border-stone-300">
                    {currentRecord.content_hash || 'No content hash'}
                  </div>
                </div>

                {/* Upstream References */}
                <div className="p-3.5 rounded-xl border-2 border-ink bg-[#FFFDF6]">
                  <div className="text-xs font-bold uppercase tracking-wider text-muted mb-1 flex items-center gap-1">
                    <ArrowUpRight size={14} />
                    <span>Upstream Evidence References</span>
                  </div>
                  {currentRecord.upstream_refs && currentRecord.upstream_refs.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {currentRecord.upstream_refs.map(ref => (
                        <button
                          key={ref}
                          type="button"
                          onClick={() => evidence[ref] && setSelectedRecordId(ref)}
                          className="font-mono text-xs px-2.5 py-1 rounded-md border border-ink bg-mustard/20 hover:bg-mustard text-ink font-bold transition-colors"
                        >
                          {ref}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-muted italic mt-2">
                      None (root stage capture)
                    </div>
                  )}
                </div>
              </div>

              {/* Inputs Table with SHA-256 */}
              <div>
                <h4 className="font-serif text-base font-bold text-ink mb-2 flex items-center gap-1.5">
                  <FileCode size={16} />
                  <span>Content-Addressed Inputs ({currentRecord.inputs ? currentRecord.inputs.length : 0})</span>
                </h4>

                {currentRecord.inputs && currentRecord.inputs.length > 0 ? (
                  <div className="overflow-x-auto border-2 border-ink rounded-xl bg-white">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="border-b-2 border-ink bg-stone-100 font-bold uppercase text-stone-700">
                          <th className="py-2 px-3">File Reference</th>
                          <th className="py-2 px-3">Kind</th>
                          <th className="py-2 px-3">SHA-256 Digest</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-stone-200">
                        {currentRecord.inputs.map((inp, i) => (
                          <tr key={i} className="font-mono hover:bg-amber-50/50">
                            <td className="py-2 px-3 font-semibold text-ink">{inp.ref}</td>
                            <td className="py-2 px-3 text-muted capitalize">{inp.kind || 'file'}</td>
                            <td className="py-2 px-3 font-mono text-[11px] text-stone-800">
                              {inp.sha256 ? (
                                <span title={inp.sha256}>{truncateHash(inp.sha256, 12, 8)}</span>
                              ) : (
                                <span className="text-muted">null (synthetic)</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="p-3 text-xs text-muted bg-stone-50 border border-stone-200 rounded-lg">
                    No discrete file inputs recorded for this evidence record.
                  </div>
                )}
              </div>

              {/* Payload Details */}
              {currentRecord.payload && Object.keys(currentRecord.payload).length > 0 && (
                <div>
                  <h4 className="font-serif text-base font-bold text-ink mb-2">
                    Evidence Payload Attributes
                  </h4>
                  <pre className="font-mono text-xs bg-stone-900 text-stone-100 p-3 rounded-xl overflow-x-auto border-2 border-ink">
                    {JSON.stringify(currentRecord.payload, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ) : (
            <div className="p-6 text-center text-[#D1CBBF] border border-[#5E5A52] rounded-xl">
              Record not loaded in evidence store.
            </div>
          )}
        </div>
      )}

      {/* Audit Transitions Timeline */}
      {transitions.length > 0 && (
        <div className="space-y-4 pt-4 border-t border-[#5E5A52]">
          <h3 className="font-serif text-xl md:text-2xl text-cream font-bold flex items-center gap-2">
            <History size={20} className="text-mustard" />
            <span>Workflow State Audit Trail (`transitions`)</span>
          </h3>

          <div className="border-2 border-ink rounded-card bg-peach text-ink p-5 md:p-6 shadow-[4px_4px_0_#FFF6DE]">
            <ol className="relative border-l-2 border-ink ml-3 space-y-4">
              {transitions.map((tr, idx) => (
                <li key={idx} className="ml-5">
                  <span className="absolute -left-[9px] mt-1.5 w-4 h-4 rounded-full border-2 border-ink bg-mustard" />
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-card border border-ink">
                      {tr.event}
                    </span>
                    {tr.stage && (
                      <span className="text-xs font-semibold px-2 py-0.5 rounded bg-ink text-cream">
                        {tr.stage}
                      </span>
                    )}
                    <span className="text-xs text-stone-700 font-mono">
                      {formatTimestamp(tr.at)}
                    </span>
                  </div>
                  {tr.detail && (
                    <p className="mt-1 text-xs font-mono text-stone-800 break-words">
                      {tr.detail}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </div>
  )
}
