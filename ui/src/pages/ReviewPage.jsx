import React, { useState, useEffect } from 'react'
import { useSession } from '../context/SessionContext'
import Band from '../components/Band'
import OverridePanel from '../components/OverridePanel'
import VerdictBadge from '../components/VerdictBadge'
import ErrorBanner from '../components/ErrorBanner'
import { getWorkflowEvidence, applyOverride, resumeWorkflow } from '../api/client'
import { ClipboardList, UserCheck, Play, Search, AlertTriangle, ShieldCheck, CheckCircle2 } from 'lucide-react'

// Built-in review scenarios from examples/
const DEFAULT_REVIEW_CANDIDATES = [
  {
    workflow_id: 'WF-org_demo_bravo-UNIT-0012',
    org_id: 'org_demo_bravo',
    unit_id: 'UNIT-0012',
    label: 'Bravo UNIT-0012 (Prep Uncertain Barcode)',
    defaultVerdict: 'PASS',
    suggestedReason: 'Re-inspected label photo; barcode is verified and scans correctly',
  },
]

export default function ReviewPage({ className = '' }) {
  const { org, operator, sessionWorkflows, updateWorkflow } = useSession()

  const [selectedWfId, setSelectedWfId] = useState('')
  const [customWfId, setCustomWfId] = useState('')
  const [currentWfData, setCurrentWfData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [successMsg, setSuccessMsg] = useState('')

  // Filter known review candidates for the active tenant
  const activeCandidates = [
    ...DEFAULT_REVIEW_CANDIDATES.filter((c) => c.org_id === org),
    ...sessionWorkflows
      .filter((w) => w.org_id === org && (w.status === 'BLOCKED' || w.final_outcome?.outcome === 'NEEDS_REVIEW' || w.status === 'FAILED'))
      .map((w) => ({
        workflow_id: w.workflow_id,
        org_id: w.org_id,
        unit_id: w.subject_id,
        label: `${w.workflow_id} (${w.status} / ${w.final_outcome?.outcome || 'UNKNOWN'})`,
      })),
  ]

  // Remove duplicates by workflow_id
  const uniqueCandidates = Array.from(new Map(activeCandidates.map((c) => [c.workflow_id, c])).values())

  const loadWorkflowDetails = async (wfId) => {
    if (!wfId) return
    try {
      setLoading(true)
      setError(null)
      setSuccessMsg('')
      const bundle = await getWorkflowEvidence(wfId)
      setCurrentWfData(bundle)
      setSelectedWfId(wfId)
    } catch (err) {
      setError(err)
      setCurrentWfData(null)
    } finally {
      setLoading(false)
    }
  }

  // When org changes, reset selection
  useEffect(() => {
    setSelectedWfId('')
    setCurrentWfData(null)
    setError(null)
    setSuccessMsg('')
    if (uniqueCandidates.length > 0) {
      setSelectedWfId(uniqueCandidates[0].workflow_id)
      loadWorkflowDetails(uniqueCandidates[0].workflow_id)
    }
  }, [org])

  const handleSelectWf = (wfId) => {
    setSelectedWfId(wfId)
    loadWorkflowDetails(wfId)
  }

  const handleCustomSearch = (e) => {
    e.preventDefault()
    if (customWfId.trim()) {
      handleSelectWf(customWfId.trim())
    }
  }

  const handleOverrideSubmit = async ({ record_id, new_verdict, actor, reason, new_outcome }) => {
    if (!currentWfData?.workflow?.workflow_id) return
    const wfId = currentWfData.workflow.workflow_id
    setLoading(true)
    setError(null)
    try {
      const updatedWf = await applyOverride(wfId, {
        record_id,
        new_verdict,
        actor,
        reason,
        new_outcome,
      })
      // Reload full evidence bundle so all updated references and override history are synchronized
      const bundle = await getWorkflowEvidence(wfId)
      setCurrentWfData(bundle)
      updateWorkflow(bundle.workflow || updatedWf, bundle.evidence)
      setSuccessMsg(`Decision override registered as ${updatedWf.overrides?.slice(-1)[0]?.override_id || 'new record'}.`)
    } catch (err) {
      setError(err)
      throw err
    } finally {
      setLoading(false)
    }
  }

  const handleResume = async () => {
    if (!currentWfData?.workflow?.workflow_id) return
    const wfId = currentWfData.workflow.workflow_id
    setLoading(true)
    setError(null)
    try {
      await resumeWorkflow(wfId)
      const bundle = await getWorkflowEvidence(wfId)
      setCurrentWfData(bundle)
      updateWorkflow(bundle.workflow, bundle.evidence)
      setSuccessMsg(`Workflow ${wfId} resumed successfully. Status: ${bundle.workflow?.status}. Outcome: ${bundle.workflow?.final_outcome?.outcome || 'CLEAN'}.`)
    } catch (err) {
      setError(err)
      throw err
    } finally {
      setLoading(false)
    }
  }

  const workflow = currentWfData?.workflow
  const evidence = currentWfData?.evidence || {}

  return (
    <div className={`w-full ${className}`}>
      {/* Review Queue Header: Cream band with Peach highlighted cards */}
      <Band
        color="cream"
        title="Review Queue"
        description="Units where an agent returned UNCERTAIN and a person must decide. Record who decided and why, then resume the workflow."
      >
        {error && (
          <ErrorBanner
            error={error}
            onDismiss={() => setError(null)}
            title="Review Queue Error"
          />
        )}

        {successMsg && (
          <div className="card-signature p-4 my-4 bg-[#2E9E6B]/15 border-2 border-[#2E9E6B] text-[#1B6F49] flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-sm">
              <CheckCircle2 size={18} />
              <span>{successMsg}</span>
            </div>
            <button
              type="button"
              onClick={() => setSuccessMsg('')}
              className="text-xs font-mono underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Workflow Selection & Search */}
        <div className="card-signature p-6 bg-card mb-8">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-4">
            <div>
              <h3 className="font-serif text-xl font-bold text-ink">
                Reviewable Cases ({org})
              </h3>
              <p className="text-xs text-muted">
                Workflows requiring manual decision or halted by policy.
              </p>
            </div>

            {/* Direct Workflow ID Lookup */}
            <form onSubmit={handleCustomSearch} className="flex items-center gap-2">
              <input
                type="text"
                value={customWfId}
                onChange={(e) => setCustomWfId(e.target.value)}
                placeholder="Lookup WF-ID..."
                className="px-3 py-1.5 border-2 border-ink rounded-xl font-mono text-xs bg-white focus:outline-none"
              />
              <button type="submit" className="btn-secondary text-xs py-1.5 px-3">
                <Search size={14} />
                <span>Fetch</span>
              </button>
            </form>
          </div>

          {/* Quick Queue Cards */}
          {uniqueCandidates.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {uniqueCandidates.map((c) => {
                const isSelected = selectedWfId === c.workflow_id
                return (
                  <button
                    key={c.workflow_id}
                    type="button"
                    onClick={() => handleSelectWf(c.workflow_id)}
                    className={`p-3.5 rounded-xl border-2 text-left transition-all flex flex-col justify-between ${
                      isSelected
                        ? 'border-ink bg-peach shadow-[3px_3px_0_var(--ink)] -translate-y-0.5'
                        : 'border-ink/40 bg-white hover:bg-stone-50'
                    }`}
                  >
                    <div>
                      <div className="font-mono text-xs font-bold text-ink truncate mb-1">
                        {c.workflow_id}
                      </div>
                      <div className="text-xs text-stone-700">
                        {c.label}
                      </div>
                    </div>
                    <div className="mt-2 text-[10px] text-muted font-mono">
                      Unit: {c.unit_id}
                    </div>
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="p-6 text-center text-muted border border-dashed border-stone-300 rounded-xl text-sm">
              No pending blocked workflows found in current session for {org}. Run a case or fetch by ID.
            </div>
          )}
        </div>

        {/* Loaded Workflow Review Workspace */}
        {loading && !workflow && (
          <div className="card-signature p-12 text-center bg-card flex flex-col items-center justify-center gap-3">
            <div className="w-10 h-10 rounded-full border-4 border-ink border-t-mustard animate-spin" />
            <span className="font-serif text-lg font-bold text-ink">
              Loading Workflow & Evidence Records...
            </span>
          </div>
        )}

        {workflow && (
          <div className="space-y-6">
            {/* Status Highlight Banner */}
            <div className="card-highlight p-5 flex flex-wrap items-center justify-between gap-4">
              <div>
                <span className="text-xs uppercase font-bold tracking-wider text-ink/70">
                  Active Workflow Under Review
                </span>
                <h3 className="font-mono text-xl md:text-2xl font-bold text-ink">
                  {workflow.workflow_id}
                </h3>
                <p className="text-xs text-ink/80 mt-0.5">
                  Status: <strong>{workflow.status}</strong> • Reason: {workflow.status_reason || '—'}
                </p>
              </div>

              <div className="flex items-center gap-3">
                <VerdictBadge
                  verdict={workflow.final_outcome?.verdict || (workflow.status === 'COMPLETED' ? 'PASS' : 'UNCERTAIN')}
                  size="md"
                />
                {workflow.final_outcome?.outcome && (
                  <span className="font-mono text-xs font-bold px-2.5 py-1 rounded-lg border-2 border-ink bg-card text-ink shadow-xs">
                    {workflow.final_outcome.outcome}
                  </span>
                )}
              </div>
            </div>

            {/* Override Panel */}
            <OverridePanel
              workflow={workflow}
              evidence={evidence}
              initialActor={operator}
              onSubmitOverride={handleOverrideSubmit}
              onResumeWorkflow={handleResume}
              loading={loading}
            />
          </div>
        )}
      </Band>
    </div>
  )
}
