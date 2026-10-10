import React, { useState } from 'react'
import VerdictBadge from './VerdictBadge'
import CheckTable from './CheckTable'
import { formatTimestamp, truncateHash } from '../lib/format'
import {
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Shield,
  Clock,
  Cpu,
  Layers,
  FileText,
  Image as ImageIcon,
  UserCheck,
  AlertTriangle,
  ExternalLink,
} from 'lucide-react'

/**
 * Shared Evidence Record Panel
 *
 * Displays:
 * - record_id (with copy button)
 * - agent_id, stage, org_id, unit_id, workflow_id
 * - captured_at, produced_at
 * - verdict & decision outcome, needs_human badge
 * - per-check table (key, verdict, confidence, expected vs observed, detail)
 * - input image refs with sha256
 * - model info & calls
 * - content hash
 * - order lines checked
 * - collapsible "View raw JSON"
 */
export default function EvidenceRecordPanel({ evidence, className = '' }) {
  const [copiedKey, setCopiedKey] = useState(null)
  const [jsonOpen, setJsonOpen] = useState(false)

  if (!evidence) {
    return null
  }

  const copyToClipboard = (text, key) => {
    if (!text) return
    navigator.clipboard.writeText(text).then(() => {
      setCopiedKey(key)
      setTimeout(() => setCopiedKey(null), 2000)
    })
  }

  const decision = evidence.decision || {}
  const subject = evidence.subject || {}
  const model = evidence.model || {}
  const inputs = Array.isArray(evidence.inputs) ? evidence.inputs : []
  const checks = Array.isArray(evidence.checks) ? evidence.checks : []
  const payload = evidence.payload || {}
  const orderLines = payload.order_lines || evidence.context?.order_lines || subject.refs?.order_lines || null
  const orderId = payload.order_id || subject.refs?.order_id || null

  return (
    <div className={`card-signature bg-card border-2 border-ink rounded-xl p-5 md:p-6 shadow-md space-y-6 ${className}`}>
      {/* Header with Record ID and Verdict */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-rule pb-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs uppercase tracking-wider font-bold text-muted">Evidence Record</span>
            <span className="font-mono text-xs px-2 py-0.5 rounded bg-stone-200/80 text-ink uppercase font-semibold">
              {evidence.stage || 'stage'}
            </span>
            {evidence.status && (
              <span
                className={`text-xs px-2 py-0.5 rounded font-mono font-bold uppercase ${
                  evidence.status === 'completed'
                    ? 'bg-emerald-100 text-emerald-800'
                    : evidence.status === 'error'
                    ? 'bg-rose-100 text-rose-800'
                    : 'bg-amber-100 text-amber-800'
                }`}
              >
                {evidence.status}
              </span>
            )}
            {decision.needs_human && (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-900 border border-amber-300 font-bold">
                <AlertTriangle size={12} className="text-amber-700" />
                <span>Needs Human Review</span>
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <span className="font-mono font-bold text-lg md:text-xl text-ink break-all">
              {evidence.record_id}
            </span>
            <button
              onClick={() => copyToClipboard(evidence.record_id, 'record_id')}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-ink/40 bg-stone-100 hover:bg-stone-200 text-ink transition-colors min-h-[36px]"
              title="Copy Record ID"
            >
              {copiedKey === 'record_id' ? (
                <>
                  <Check size={12} className="text-emerald-700" />
                  <span className="text-emerald-800 font-medium">Copied!</span>
                </>
              ) : (
                <>
                  <Copy size={12} />
                  <span>Copy ID</span>
                </>
              )}
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3 self-start sm:self-center">
          <VerdictBadge verdict={decision.verdict || 'UNCERTAIN'} size="lg" />
        </div>
      </div>

      {/* Outcome / Reason Banner if present */}
      {(decision.outcome || decision.reason || evidence.error) && (
        <div
          className={`p-3.5 rounded-lg border text-sm ${
            evidence.error
              ? 'bg-rose-50 border-rose-200 text-rose-950'
              : decision.verdict === 'PASS'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-950'
              : decision.verdict === 'FAIL'
              ? 'bg-rose-50 border-rose-200 text-rose-950'
              : 'bg-amber-50 border-amber-200 text-amber-950'
          }`}
        >
          <div className="flex items-start gap-2">
            <Shield size={16} className="mt-0.5 shrink-0" />
            <div className="min-w-0">
              {decision.outcome && (
                <div className="font-bold text-xs uppercase tracking-wider mb-0.5">
                  Outcome: {decision.outcome}
                </div>
              )}
              {evidence.error ? (
                <div className="text-xs">
                  <span className="font-semibold">{evidence.error.code || 'Error'}: </span>
                  <span>{evidence.error.message || 'Stage execution failed'}</span>
                </div>
              ) : (
                decision.reason && <div className="text-xs text-ink/80">{decision.reason}</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Metadata Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 text-xs">
        <div className="p-3 bg-stone-50 rounded-lg border border-stone-200">
          <div className="text-muted uppercase tracking-wider font-semibold mb-1">Agent ID</div>
          <div className="font-mono text-ink font-medium break-all">{evidence.agent_id || '—'}</div>
        </div>

        <div className="p-3 bg-stone-50 rounded-lg border border-stone-200">
          <div className="text-muted uppercase tracking-wider font-semibold mb-1">Organisation</div>
          <div className="font-mono text-ink font-medium">{subject.org_id || '—'}</div>
        </div>

        <div className="p-3 bg-stone-50 rounded-lg border border-stone-200">
          <div className="text-muted uppercase tracking-wider font-semibold mb-1">Unit ID</div>
          <div className="font-mono text-ink font-medium">{subject.subject_id || subject.unit_id || '—'}</div>
        </div>

        <div className="p-3 bg-stone-50 rounded-lg border border-stone-200">
          <div className="text-muted uppercase tracking-wider font-semibold mb-1">Workflow ID</div>
          <div className="font-mono text-ink font-medium break-all">{evidence.workflow_id || '—'}</div>
        </div>

        {orderId && (
          <div className="p-3 bg-stone-50 rounded-lg border border-stone-200">
            <div className="text-muted uppercase tracking-wider font-semibold mb-1">Order ID</div>
            <div className="font-mono text-ink font-medium break-all">{orderId}</div>
          </div>
        )}

        <div className="p-3 bg-stone-50 rounded-lg border border-stone-200">
          <div className="text-muted uppercase tracking-wider font-semibold mb-1 flex items-center gap-1">
            <Clock size={12} />
            <span>Captured At</span>
          </div>
          <div className="font-mono text-ink font-medium">
            {evidence.captured_at ? formatTimestamp(evidence.captured_at) : '—'}
          </div>
        </div>

        <div className="p-3 bg-stone-50 rounded-lg border border-stone-200">
          <div className="text-muted uppercase tracking-wider font-semibold mb-1 flex items-center gap-1">
            <Clock size={12} />
            <span>Produced At</span>
          </div>
          <div className="font-mono text-ink font-medium">
            {evidence.produced_at ? formatTimestamp(evidence.produced_at) : '—'}
          </div>
        </div>

        <div className="p-3 bg-stone-50 rounded-lg border border-stone-200">
          <div className="text-muted uppercase tracking-wider font-semibold mb-1 flex items-center gap-1">
            <Cpu size={12} />
            <span>Model Execution</span>
          </div>
          <div className="font-mono text-ink font-medium">
            {model.name ? `${model.name} (${model.calls ?? 0} calls)` : 'rules / stub'}
            {evidence.latency_ms !== undefined && evidence.latency_ms !== null && ` • ${evidence.latency_ms}ms`}
          </div>
        </div>
      </div>

      {/* Order Lines Checked (if present) */}
      {orderLines && (
        <div className="p-3 bg-amber-50/50 rounded-lg border border-amber-200/80">
          <div className="text-xs uppercase tracking-wider font-bold text-amber-900 mb-1">
            Order Lines Checked
          </div>
          <div className="font-mono text-xs text-ink break-all">
            {typeof orderLines === 'string' ? orderLines : JSON.stringify(orderLines)}
          </div>
        </div>
      )}

      {/* Checks Table */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="font-serif font-bold text-ink text-sm flex items-center gap-2">
            <span>Per-Check Evaluations</span>
            <span className="text-xs font-mono font-normal text-muted">
              ({checks.length} checks)
            </span>
          </h4>
        </div>
        <CheckTable checks={checks} />
      </div>

      {/* Content-Addressed Inputs (Images) */}
      <div className="space-y-2">
        <h4 className="font-serif font-bold text-ink text-sm flex items-center gap-2">
          <ImageIcon size={16} />
          <span>Input Media & Hashes (Content-Addressed)</span>
          <span className="text-xs font-mono font-normal text-muted">
            ({inputs.length} {inputs.length === 1 ? 'file' : 'files'})
          </span>
        </h4>
        {inputs.length === 0 ? (
          <div className="py-3 px-4 text-xs text-muted bg-stone-50 rounded-lg border border-dashed border-stone-300">
            No media inputs registered for this record.
          </div>
        ) : (
          <div className="space-y-2">
            {inputs.map((inp, idx) => (
              <div
                key={idx}
                className="p-3 bg-stone-50 rounded-lg border border-stone-200 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-xs"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono font-semibold text-ink break-all">{inp.ref}</span>
                    {inp.kind && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] uppercase font-mono bg-stone-200 text-stone-700">
                        {inp.kind}
                      </span>
                    )}
                  </div>
                  {inp.sha256 && (
                    <div className="font-mono text-[11px] text-muted break-all mt-0.5">
                      SHA-256: <span className="text-ink">{inp.sha256}</span>
                    </div>
                  )}
                </div>

                {inp.sha256 && (
                  <button
                    onClick={() => copyToClipboard(inp.sha256, `sha_${idx}`)}
                    className="self-start sm:self-center shrink-0 inline-flex items-center gap-1 px-2 py-1 text-[11px] rounded border border-stone-300 bg-white hover:bg-stone-100 text-ink transition-colors min-h-[32px]"
                    title="Copy SHA-256 hash"
                  >
                    {copiedKey === `sha_${idx}` ? (
                      <>
                        <Check size={11} className="text-emerald-700" />
                        <span className="text-emerald-800">Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy size={11} />
                        <span>Copy SHA</span>
                      </>
                    )}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Content Hash Verification */}
      {evidence.content_hash && (
        <div className="p-3.5 bg-stone-100 rounded-lg border border-stone-300 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 text-xs">
          <div className="min-w-0">
            <div className="text-muted uppercase tracking-wider font-semibold mb-0.5 flex items-center gap-1.5">
              <Shield size={12} className="text-emerald-700" />
              <span>Record Content Hash (Tamper-Sealed)</span>
            </div>
            <div className="font-mono text-ink text-xs break-all">
              {evidence.content_hash}
            </div>
          </div>
          <button
            onClick={() => copyToClipboard(evidence.content_hash, 'content_hash')}
            className="self-start sm:self-center shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border border-ink/40 bg-white hover:bg-stone-50 text-ink transition-colors min-h-[36px]"
          >
            {copiedKey === 'content_hash' ? (
              <>
                <Check size={12} className="text-emerald-700" />
                <span className="text-emerald-800 font-medium">Copied Hash!</span>
              </>
            ) : (
              <>
                <Copy size={12} />
                <span>Copy Hash</span>
              </>
            )}
          </button>
        </div>
      )}

      {/* Collapsible Raw JSON */}
      <div className="border-t border-rule pt-4">
        <button
          onClick={() => setJsonOpen(!jsonOpen)}
          className="w-full flex items-center justify-between text-left text-xs font-semibold text-muted hover:text-ink transition-colors py-1.5"
        >
          <span className="flex items-center gap-1.5">
            <FileText size={14} />
            <span>{jsonOpen ? 'Hide' : 'View'} Raw Evidence JSON</span>
          </span>
          {jsonOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>

        {jsonOpen && (
          <div className="mt-3 relative">
            <button
              onClick={() => copyToClipboard(JSON.stringify(evidence, null, 2), 'raw_json')}
              className="absolute top-2 right-2 inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded bg-stone-800 hover:bg-stone-700 text-stone-200 border border-stone-700 transition-colors"
            >
              {copiedKey === 'raw_json' ? (
                <>
                  <Check size={12} className="text-emerald-400" />
                  <span className="text-emerald-300">Copied JSON!</span>
                </>
              ) : (
                <>
                  <Copy size={12} />
                  <span>Copy JSON</span>
                </>
              )}
            </button>
            <pre className="font-mono text-xs bg-stone-900 text-stone-100 p-4 rounded-xl overflow-x-auto max-h-96 leading-relaxed">
              {JSON.stringify(evidence, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
