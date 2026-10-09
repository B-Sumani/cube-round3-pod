import React, { useState } from 'react'
import VerdictBadge from './VerdictBadge'
import CheckTable from './CheckTable'
import { formatTimestamp } from '../lib/format'
import { ShieldCheck, UserCheck, Play, CheckCircle2, AlertTriangle, ArrowRight, CornerDownRight } from 'lucide-react'

/**
 * OverridePanel shows original evidence beside the override form:
 * - Actor, reason, verdict required
 * - Then resume action
 * - Original evidence stays visible; the override appears as a new record
 */
export default function OverridePanel({
  workflow,
  evidence = {},
  initialActor = '',
  onSubmitOverride,
  onResumeWorkflow,
  loading = false,
  className = '',
}) {
  const [recordId, setRecordId] = useState('')
  const [newVerdict, setNewVerdict] = useState('PASS')
  const [newOutcome, setNewOutcome] = useState('')
  const [actor, setActor] = useState(initialActor || '')
  const [reason, setReason] = useState('')
  const [validationError, setValidationError] = useState('')
  const [lastOverrideSuccess, setLastOverrideSuccess] = useState(false)

  React.useEffect(() => {
    if (initialActor) {
      setActor(initialActor)
    }
  }, [initialActor])

  const recordIds = workflow?.evidence_references || Object.keys(evidence)
  const uncertainRecordId = recordIds.find(
    (rid) => evidence[rid]?.decision?.verdict === 'UNCERTAIN' || evidence[rid]?.decision?.needs_human
  )
  const defaultRecordId = recordId || uncertainRecordId || recordIds[0] || ''
  const selectedRecord = evidence[defaultRecordId] || null
  const existingOverrides = workflow?.overrides || []

  const handleSubmit = async (e) => {
    e.preventDefault()
    setValidationError('')
    setLastOverrideSuccess(false)

    if (!defaultRecordId) {
      setValidationError('Please select an evidence record to override.')
      return
    }
    if (!actor.trim()) {
      setValidationError('Actor identity is required (e.g. op_chen or your username).')
      return
    }
    if (!reason.trim()) {
      setValidationError('Reason for override is required (e.g. manual physical verification, photo retaken).')
      return
    }

    try {
      await onSubmitOverride({
        record_id: defaultRecordId,
        new_verdict: newVerdict,
        actor: actor.trim(),
        reason: reason.trim(),
        new_outcome: newOutcome.trim() || undefined,
      })
      setLastOverrideSuccess(true)
      setReason('')
    } catch (err) {
      setValidationError(err.message || 'Failed to submit override.')
    }
  }

  const handleResume = async () => {
    if (onResumeWorkflow) {
      await onResumeWorkflow()
    }
  }

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Existing Overrides Banner / Records */}
      {existingOverrides.length > 0 && (
        <div className="card-signature p-5 bg-card">
          <h3 className="font-serif text-lg font-bold text-ink mb-3 flex items-center gap-2">
            <ShieldCheck size={20} className="text-[#2E9E6B]" />
            <span>Applied Overrides Audit Log ({existingOverrides.length})</span>
          </h3>
          <div className="space-y-3">
            {existingOverrides.map((ovr, idx) => (
              <div key={ovr.override_id || idx} className="p-3.5 rounded-xl border-2 border-ink bg-white text-xs">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold px-2 py-0.5 rounded bg-mustard border border-ink text-ink">
                      {ovr.override_id}
                    </span>
                    <span className="text-muted">by</span>
                    <strong className="text-ink font-mono">{ovr.actor}</strong>
                    <span className="text-muted">• {formatTimestamp(ovr.at)}</span>
                  </div>

                  <div className="flex items-center gap-1.5 font-bold">
                    <VerdictBadge verdict={ovr.previous_verdict || ovr.original_verdict} size="sm" />
                    <ArrowRight size={14} className="text-muted" />
                    <VerdictBadge verdict={ovr.new_verdict} size="sm" />
                  </div>
                </div>

                <div className="font-medium text-stone-800 mt-1">
                  <span className="text-muted">Reason:</span> "{ovr.reason}"
                </div>

                <div className="text-[11px] text-muted font-mono mt-1 flex items-center gap-1">
                  <CornerDownRight size={12} />
                  <span>Target Record: {ovr.supersedes?.record_id}</span>
                  {ovr.new_outcome && <span>• New Outcome: {ovr.new_outcome}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Side-by-Side: Original Evidence beside Override Form */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Original Evidence (lg:col-span-7) */}
        <div className="lg:col-span-7 card-signature p-5 md:p-6 bg-card space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b-2 border-ink">
            <div>
              <span className="text-xs uppercase font-bold tracking-wider text-muted">
                Original Evidence
              </span>
              <h3 className="font-serif text-xl font-bold text-ink">
                Record Inspection
              </h3>
            </div>
            {selectedRecord && (
              <VerdictBadge verdict={selectedRecord.decision?.verdict} size="md" />
            )}
          </div>

          {/* Record Selector if multiple */}
          {recordIds.length > 1 && (
            <div>
              <label htmlFor="select-record" className="block text-xs font-bold uppercase tracking-wider text-muted mb-1">
                Select Evidence Record:
              </label>
              <select
                id="select-record"
                value={defaultRecordId}
                onChange={(e) => setRecordId(e.target.value)}
                className="w-full px-3 py-2 border-2 border-ink rounded-xl font-mono text-sm bg-white focus:outline-none"
              >
                {recordIds.map(rid => {
                  const r = evidence[rid]
                  return (
                    <option key={rid} value={rid}>
                      {rid} ({r?.stage || 'unknown'} - {r?.decision?.verdict || 'PENDING'})
                    </option>
                  )
                })}
              </select>
            </div>
          )}

          {/* Selected Record Content */}
          {selectedRecord ? (
            <div className="space-y-4">
              <div className="p-3.5 rounded-xl border border-stone-300 bg-stone-50 text-xs space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-muted">Record ID:</span>
                  <span className="font-mono font-bold text-ink">{selectedRecord.record_id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Stage / Agent:</span>
                  <span className="font-mono text-ink">{selectedRecord.stage} / {selectedRecord.agent_id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">Original Decision Verdict:</span>
                  <span className="font-bold text-ink">{selectedRecord.decision?.verdict}</span>
                </div>
                {selectedRecord.decision?.reason && (
                  <div className="pt-1 border-t border-stone-200">
                    <span className="text-muted block mb-0.5">Original Agent Rationale:</span>
                    <span className="italic text-stone-800">"{selectedRecord.decision.reason}"</span>
                  </div>
                )}
              </div>

              {/* Checks */}
              {selectedRecord.checks && selectedRecord.checks.length > 0 && (
                <div>
                  <h4 className="text-xs uppercase font-bold tracking-wider text-muted mb-2">
                    Original Automated Checks
                  </h4>
                  <CheckTable checks={selectedRecord.checks} />
                </div>
              )}
            </div>
          ) : (
            <div className="p-8 text-center text-muted border border-dashed border-stone-300 rounded-xl">
              No evidence record selected.
            </div>
          )}
        </div>

        {/* Right Column: Override Form (Peach Highlighted Card) (lg:col-span-5) */}
        <div className="lg:col-span-5 card-highlight p-5 md:p-6 space-y-5">
          <div>
            <span className="text-xs uppercase font-bold tracking-wider text-ink/70">
              Human In The Loop
            </span>
            <h3 className="font-serif text-xl font-bold text-ink flex items-center gap-2">
              <UserCheck size={22} />
              <span>Apply Decision Override</span>
            </h3>
            <p className="mt-1 text-xs text-ink/80 leading-relaxed">
              Overrides create a new authoritative audit entry. Original evidence records remain immutable.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Target Record */}
            <div>
              <label htmlFor="override-target-record" className="block text-xs font-bold uppercase tracking-wider text-ink mb-1">
                Target Record ID
              </label>
              <input
                id="override-target-record"
                type="text"
                readOnly
                value={defaultRecordId}
                className="w-full px-3 py-2 border-2 border-ink rounded-xl font-mono text-sm bg-white/70 text-ink cursor-not-allowed"
              />
            </div>

            {/* New Verdict */}
            <div>
              <label htmlFor="override-new-verdict" className="block text-xs font-bold uppercase tracking-wider text-ink mb-1">
                New Verdict *
              </label>
              <div className="grid grid-cols-3 gap-2">
                {['PASS', 'FAIL', 'UNCERTAIN'].map(v => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setNewVerdict(v)}
                    className={`py-2 px-2 text-xs font-bold rounded-xl border-2 transition-all flex items-center justify-center gap-1.5 ${
                      newVerdict === v
                        ? 'border-ink bg-mustard shadow-[2px_2px_0_var(--ink)] -translate-y-0.5'
                        : 'border-ink/60 bg-white/80 hover:bg-white'
                    }`}
                  >
                    <VerdictBadge verdict={v} size="sm" />
                  </button>
                ))}
              </div>
            </div>

            {/* New Outcome (optional) */}
            <div>
              <label htmlFor="new-outcome" className="block text-xs font-bold uppercase tracking-wider text-ink mb-1">
                New Outcome (Optional)
              </label>
              <input
                id="new-outcome"
                type="text"
                value={newOutcome}
                onChange={(e) => setNewOutcome(e.target.value)}
                placeholder="e.g. compliant_manual_verified"
                className="w-full px-3 py-2 border-2 border-ink rounded-xl text-sm bg-white focus:outline-none"
              />
            </div>

            {/* Actor identity (Required) */}
            <div>
              <label htmlFor="actor-id" className="block text-xs font-bold uppercase tracking-wider text-ink mb-1">
                Operator / Actor Name *
              </label>
              <input
                id="actor-id"
                type="text"
                required
                value={actor}
                onChange={(e) => setActor(e.target.value)}
                placeholder="e.g. op_chen, op_amira"
                className="w-full px-3 py-2 border-2 border-ink rounded-xl text-sm bg-white focus:outline-none"
              />
            </div>

            {/* Reason (Required) */}
            <div>
              <label htmlFor="override-reason" className="block text-xs font-bold uppercase tracking-wider text-ink mb-1">
                Rationale / Justification *
              </label>
              <textarea
                id="override-reason"
                required
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Explain why this decision is being modified (e.g. retook physical scan; barcode verified manually)..."
                className="w-full px-3 py-2 border-2 border-ink rounded-xl text-sm bg-white focus:outline-none"
              />
            </div>

            {validationError && (
              <div className="p-3 bg-red-100 border border-[#D64545] rounded-xl text-xs text-[#A02222] font-semibold">
                {validationError}
              </div>
            )}

            {lastOverrideSuccess && (
              <div className="p-3 bg-[#2E9E6B]/20 border border-[#2E9E6B] rounded-xl text-xs text-[#1B6F49] font-bold flex items-center gap-1.5">
                <CheckCircle2 size={16} />
                <span>Override successfully registered into workflow!</span>
              </div>
            )}

            <div className="pt-2 flex flex-col sm:flex-row gap-3">
              <button
                type="submit"
                disabled={loading}
                className="btn-primary flex-1 py-2.5 text-sm"
              >
                {loading ? 'Submitting Override...' : 'Submit Override'}
              </button>
            </div>
          </form>

          {/* Resume Workflow Section */}
          <div className="pt-4 border-t-2 border-ink/30">
            <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
              <div className="text-xs text-ink/80">
                <strong className="block text-ink">Ready to continue?</strong>
                <span>Resume remaining pending stages.</span>
              </div>
              <button
                type="button"
                onClick={handleResume}
                disabled={loading}
                className="btn-secondary w-full sm:w-auto text-sm py-2 px-4 flex items-center justify-center gap-1.5"
              >
                <Play size={14} className="fill-current" />
                <span>Resume Workflow</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
