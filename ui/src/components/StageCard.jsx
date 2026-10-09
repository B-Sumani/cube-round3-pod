import React, { useState } from 'react'
import VerdictBadge from './VerdictBadge'
import CheckTable from './CheckTable'
import { formatDuration, formatCurrency } from '../lib/format'
import { ChevronDown, ChevronUp, Cpu, Clock, AlertTriangle, ShieldCheck, UserCheck } from 'lucide-react'

/**
 * Detailed Stage Card showing:
 * - Verdict badge
 * - Checks table
 * - Model info (name, version, calls, cost)
 * - Duration, agent ID, error or skipped state
 */
export default function StageCard({ stageResult, evidenceRecord, className = '' }) {
  const [expanded, setExpanded] = useState(true)

  if (!stageResult) return null

  const {
    stage,
    agent_id,
    state,
    skipped_reason,
    record_id,
    verdict,
    outcome,
    needs_human,
    next_step_recommendation,
    duration_ms,
    runs,
    attempts,
    error,
  } = stageResult

  const model = evidenceRecord?.model || {}
  const checks = evidenceRecord?.checks || []
  const decision = evidenceRecord?.decision || {}

  const isSkipped = state === 'skipped'
  const isError = state === 'error'

  return (
    <div
      className={`card-signature overflow-hidden transition-shadow ${
        isError ? 'border-[#D64545] shadow-[4px_4px_0_#D64545]' : ''
      } ${className}`}
    >
      {/* Header bar */}
      <div className="p-4 sm:p-5 flex flex-wrap items-center justify-between gap-3 border-b-2 border-ink bg-card">
        <div className="flex items-center gap-3">
          <span className="w-8 h-8 rounded-full border-2 border-ink flex items-center justify-center font-serif font-bold text-sm bg-mustard text-ink">
            {stage ? stage.charAt(0).toUpperCase() : '?'}
          </span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-serif text-lg md:text-xl font-bold capitalize text-ink">
                {stage}
              </h3>
              {record_id && (
                <span className="font-mono text-xs px-2 py-0.5 rounded bg-stone-100 border border-stone-300 text-ink">
                  {record_id}
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted mt-0.5">
              <span>Agent: <strong className="font-mono text-ink">{agent_id || 'none'}</strong></span>
              {duration_ms !== null && duration_ms !== undefined && (
                <>
                  <span>•</span>
                  <span className="inline-flex items-center gap-1">
                    <Clock size={12} /> {formatDuration(duration_ms)}
                  </span>
                </>
              )}
              {runs > 1 && (
                <>
                  <span>•</span>
                  <span>Runs: {runs} (Try {attempts})</span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {isSkipped ? (
            <VerdictBadge verdict="SKIPPED" size="md" />
          ) : (
            <VerdictBadge verdict={verdict || decision.verdict} size="md" />
          )}

          {needs_human && (
            <span className="inline-flex items-center gap-1 text-xs font-bold px-2 py-1 rounded bg-amber-100 text-amber-900 border border-amber-300">
              <UserCheck size={14} /> Needs Human
            </span>
          )}

          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="p-1.5 rounded-lg border border-ink hover:bg-mustard transition-colors text-ink"
            aria-label={expanded ? `Collapse ${stage} details` : `Expand ${stage} details`}
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </div>

      {/* Expanded Content */}
      {expanded && (
        <div className="p-4 sm:p-5 space-y-4 bg-white/50">
          {/* Skipped Message */}
          {isSkipped && (
            <div className="p-3 bg-stone-100 border border-stone-300 rounded-lg text-sm text-stone-700">
              <span className="font-semibold text-ink">Routing Policy Skipped:</span> {skipped_reason}
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="p-3 bg-red-50 border border-[#D64545] rounded-lg text-sm text-[#A02222]">
              <div className="font-bold flex items-center gap-1.5 mb-1">
                <AlertTriangle size={16} />
                <span>Error Code: {error.code || 'stage_error'}</span>
              </div>
              <p className="font-mono text-xs whitespace-pre-wrap">{error.message}</p>
            </div>
          )}

          {/* Outcome & Decision Summary */}
          {!isSkipped && (outcome || decision.outcome || decision.reason) && (
            <div className="p-3 bg-card border border-stone-300 rounded-lg text-sm flex flex-col sm:flex-row justify-between gap-2">
              <div>
                <span className="text-xs uppercase font-bold tracking-wider text-muted">Effective Outcome:</span>
                <span className="ml-2 font-bold font-mono text-ink">{outcome || decision.outcome || '—'}</span>
                {decision.reason && (
                  <p className="mt-1 text-xs text-stone-700 italic">"{decision.reason}"</p>
                )}
              </div>
              {next_step_recommendation && (
                <div className="text-xs sm:text-right shrink-0">
                  <span className="font-semibold text-muted">Recommendation:</span>{' '}
                  <span className="font-mono font-bold text-ink">{next_step_recommendation.action}</span>
                </div>
              )}
            </div>
          )}

          {/* Checks Table */}
          {!isSkipped && checks.length > 0 && (
            <div>
              <h4 className="text-xs uppercase font-bold tracking-wider text-muted mb-2">
                Automated Checks ({checks.length})
              </h4>
              <CheckTable checks={checks} />
            </div>
          )}

          {/* Model Statistics Footer */}
          {!isSkipped && (model.name || model.calls !== undefined) && (
            <div className="pt-2 border-t border-stone-200 flex flex-wrap items-center justify-between gap-3 text-xs text-muted">
              <div className="flex items-center gap-2">
                <Cpu size={14} className="text-ink" />
                <span>Model: <strong className="font-mono text-ink">{model.name || 'none'}</strong> (v{model.version || '0'})</span>
              </div>
              <div className="flex items-center gap-4">
                <span>Calls: <strong className="text-ink">{model.calls ?? 0}</strong></span>
                <span>Cost: <strong className="text-ink">{formatCurrency(model.cost_usd ?? 0)}</strong></span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
