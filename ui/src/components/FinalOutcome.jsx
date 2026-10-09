import React from 'react'
import VerdictBadge from './VerdictBadge'
import { formatCurrency, formatTimestamp } from '../lib/format'
import { DollarSign, UserCheck, CheckCircle2, AlertOctagon, HelpCircle, Layers, ShieldCheck } from 'lucide-react'

/**
 * Final Commerce Outcome Card displaying:
 * - Real outcome name from orchestrator
 * - Verdict badge
 * - needs_human indicator
 * - Contributing records list
 * - Claimable amount (if any)
 * - Effective stage verdicts
 */
export default function FinalOutcome({ workflow, className = '' }) {
  if (!workflow) return null

  const outcomeData = workflow.final_outcome
  const status = workflow.status
  const isFailed = status === 'FAILED'
  const isHalted = Boolean(workflow.halted)

  if (!outcomeData && !isFailed) {
    return (
      <div className="card-signature p-6 text-center text-muted">
        Workflow is pending or in progress; final outcome not yet derived.
      </div>
    )
  }

  const outcomeName = outcomeData?.outcome || (isFailed ? 'FAILED' : 'INCOMPLETE')
  const verdict = outcomeData?.verdict || (isFailed ? 'FAIL' : 'UNCERTAIN')
  const reason = outcomeData?.reason || workflow.status_reason || '—'
  const claimable = outcomeData?.claimable_usd
  const needsHuman = outcomeData?.needs_human
  const isProvisional = outcomeData?.provisional
  const contributing = outcomeData?.contributing_records || []
  const effectiveVerdicts = outcomeData?.effective_verdicts || {}

  // Calculate key metrics
  const completedStages = (workflow.stage_results || []).filter(s => s.state === 'completed').length
  const totalStages = (workflow.stage_results || []).length
  const skippedStages = (workflow.stage_results || []).filter(s => s.state === 'skipped').length

  return (
    <div className={`card-signature overflow-hidden ${className}`}>
      {/* Header */}
      <div className="p-5 md:p-6 border-b-2 border-ink bg-card flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <span className="text-xs uppercase font-bold tracking-wider text-muted">
              Final Commerce Outcome
            </span>
            {isProvisional && (
              <span className="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-900 border border-amber-300 font-semibold">
                Provisional
              </span>
            )}
            {isHalted && (
              <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-900 border border-red-300 font-semibold">
                Halted at {workflow.halted.stage}
              </span>
            )}
          </div>
          <h3 className="text-2xl md:text-3xl font-serif font-bold text-ink flex items-center gap-3">
            <span>{outcomeName}</span>
          </h3>
        </div>

        <div className="flex items-center gap-3">
          <VerdictBadge verdict={verdict} size="lg" />
          {needsHuman && (
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-amber-200 border-2 border-ink text-ink font-bold text-sm shadow-sm">
              <UserCheck size={16} /> Needs Human Review
            </span>
          )}
        </div>
      </div>

      {/* Main Stats and Reason */}
      <div className="p-5 md:p-6 bg-white/70 space-y-6">
        {/* Highlighted Reason */}
        <div className="p-4 rounded-xl bg-card border-2 border-ink shadow-sm">
          <div className="text-xs uppercase font-bold tracking-wider text-muted mb-1">
            Decision Rationale
          </div>
          <p className="text-base text-ink font-medium leading-relaxed">
            {reason}
          </p>
        </div>

        {/* Key Numbers Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
          {/* Claim Amount */}
          <div className="p-3.5 rounded-xl border-2 border-ink bg-card">
            <span className="text-xs uppercase font-bold text-muted block mb-1">
              Claim Amount
            </span>
            <span className="text-xl md:text-2xl font-serif font-bold text-ink flex items-center">
              {claimable !== null && claimable !== undefined ? (
                <span className="text-[#1B6F49] font-mono">{formatCurrency(claimable)}</span>
              ) : (
                <span className="text-muted text-base font-sans font-normal">$0.00 (No claim)</span>
              )}
            </span>
          </div>

          {/* Workflow Status */}
          <div className="p-3.5 rounded-xl border-2 border-ink bg-card">
            <span className="text-xs uppercase font-bold text-muted block mb-1">
              Workflow Status
            </span>
            <span className="text-base md:text-lg font-mono font-bold text-ink uppercase">
              {status}
            </span>
          </div>

          {/* Stage Progress */}
          <div className="p-3.5 rounded-xl border-2 border-ink bg-card">
            <span className="text-xs uppercase font-bold text-muted block mb-1">
              Stages Run
            </span>
            <span className="text-xl md:text-2xl font-serif font-bold text-ink">
              {completedStages} <span className="text-sm font-sans font-normal text-muted">/ {totalStages - skippedStages} active</span>
            </span>
          </div>

          {/* Overrides Count */}
          <div className="p-3.5 rounded-xl border-2 border-ink bg-card">
            <span className="text-xs uppercase font-bold text-muted block mb-1">
              Overrides Applied
            </span>
            <span className="text-xl md:text-2xl font-serif font-bold text-ink">
              {workflow.overrides ? workflow.overrides.length : 0}
            </span>
          </div>
        </div>

        {/* Effective Verdicts & Contributing Evidence Records */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Effective Verdicts */}
          {Object.keys(effectiveVerdicts).length > 0 && (
            <div className="p-4 rounded-xl border border-ink/20 bg-stone-50">
              <h4 className="text-xs uppercase font-bold tracking-wider text-muted mb-2.5">
                Effective Stage Verdicts
              </h4>
              <div className="flex flex-wrap gap-2">
                {Object.entries(effectiveVerdicts).map(([stg, v]) => (
                  <div key={stg} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-ink bg-card text-xs">
                    <span className="font-semibold capitalize">{stg}:</span>
                    <VerdictBadge verdict={v} size="sm" />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Contributing Records */}
          {contributing.length > 0 && (
            <div className="p-4 rounded-xl border border-ink/20 bg-stone-50">
              <h4 className="text-xs uppercase font-bold tracking-wider text-muted mb-2.5">
                Contributing Evidence Records ({contributing.length})
              </h4>
              <div className="flex flex-wrap gap-2">
                {contributing.map(rid => (
                  <span
                    key={rid}
                    className="font-mono text-xs px-2.5 py-1 rounded-lg bg-mustard/30 border border-ink text-ink font-bold shadow-xs"
                  >
                    {rid}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
