import React, { useState, useEffect } from 'react'
import { useSession } from '../context/SessionContext'
import Band from '../components/Band'
import OverridePanel from '../components/OverridePanel'
import EvidenceRecordPanel from '../components/EvidenceRecordPanel'
import VerdictBadge from '../components/VerdictBadge'
import ErrorBanner from '../components/ErrorBanner'
import { getWorkflowEvidence, applyOverride, resumeWorkflow } from '../api/client'
import { formatTimestamp } from '../lib/format'
import {
  ClipboardList,
  UserCheck,
  Search,
  CheckCircle2,
  Copy,
  Check,
  ArrowRight,
  Upload,
  AlertCircle,
  RefreshCw,
  Clock,
  Layers,
  CheckCheck,
} from 'lucide-react'

export default function ReviewPage({ className = '' }) {
  const {
    org,
    operator,
    reviewQueue,
    pendingCount,
    resolvedCount,
    reviewLoading,
    refreshReviewQueue,
    updateWorkflow,
  } = useSession()

  const [activeTab, setActiveTab] = useState('pending') // 'pending' | 'resolved'
  const [selectedItem, setSelectedItem] = useState(null)
  const [customWfId, setCustomWfId] = useState('')
  const [currentWfData, setCurrentWfData] = useState(null)
  const [loadingDetails, setLoadingDetails] = useState(false)
  const [error, setError] = useState(null)
  const [successMsg, setSuccessMsg] = useState('')
  const [copiedKey, setCopiedKey] = useState(null)

  const pendingItems = reviewQueue?.pending || []
  const resolvedItems = reviewQueue?.resolved || []
  const displayedItems = activeTab === 'pending' ? pendingItems : resolvedItems

  const copyToClipboard = (text, key) => {
    if (!text) return
    navigator.clipboard.writeText(text).then(() => {
      setCopiedKey(key)
      setTimeout(() => setCopiedKey(null), 2000)
    })
  }

  // Load workflow and evidence bundle when an item is selected
  const loadItemDetails = async (item) => {
    if (!item?.workflow_id) return
    setLoadingDetails(true)
    setError(null)
    setSelectedItem(item)
    try {
      const bundle = await getWorkflowEvidence(item.workflow_id, org)
      setCurrentWfData(bundle)
    } catch (err) {
      setError(err)
      setCurrentWfData(null)
    } finally {
      setLoadingDetails(false)
    }
  }

  // Direct lookup of workflow by ID
  const handleCustomSearch = async (e) => {
    e.preventDefault()
    if (!customWfId.trim()) return
    const wfId = customWfId.trim()
    setLoadingDetails(true)
    setError(null)
    setSuccessMsg('')
    try {
      const bundle = await getWorkflowEvidence(wfId, org)
      setCurrentWfData(bundle)
      setSelectedItem({
        workflow_id: wfId,
        record_id: bundle.workflow?.evidence_references?.[0] || '',
        unit_id: bundle.workflow?.subject_id || '',
        stage: bundle.workflow?.stage_results?.[0]?.stage || 'unknown',
        verdict: bundle.workflow?.final_outcome?.verdict || 'UNCERTAIN',
        reason: bundle.workflow?.status_reason || 'Manual lookup',
        status: bundle.workflow?.status === 'BLOCKED' ? 'pending' : 'resolved',
      })
    } catch (err) {
      setError(err)
      setCurrentWfData(null)
    } finally {
      setLoadingDetails(false)
    }
  }

  // Automatically select the first pending item if none selected or when tab changes
  useEffect(() => {
    if (displayedItems.length > 0) {
      const currentExists = displayedItems.some(
        (it) => it.id === selectedItem?.id || it.record_id === selectedItem?.record_id
      )
      if (!currentExists) {
        loadItemDetails(displayedItems[0])
      }
    } else {
      setSelectedItem(null)
      setCurrentWfData(null)
    }
  }, [activeTab, displayedItems.length, org])

  // Handle human decision override submission
  const handleOverrideSubmit = async ({ record_id, new_verdict, actor, reason, new_outcome }) => {
    const wfId = selectedItem?.workflow_id || currentWfData?.workflow?.workflow_id
    if (!wfId) return
    setLoadingDetails(true)
    setError(null)
    try {
      const updatedWf = await applyOverride(
        wfId,
        {
          record_id,
          new_verdict,
          actor,
          reason,
          new_outcome,
        },
        org
      )
      // Reload evidence bundle
      const bundle = await getWorkflowEvidence(wfId, org)
      setCurrentWfData(bundle)
      updateWorkflow(bundle.workflow || updatedWf, bundle.evidence)
      await refreshReviewQueue()
      setSuccessMsg(`Decision override registered as ${updatedWf.overrides?.slice(-1)[0]?.override_id || 'OVR'}. Item moved to Resolved.`)
    } catch (err) {
      setError(err)
      throw err
    } finally {
      setLoadingDetails(false)
    }
  }

  // Handle resume action
  const handleResume = async () => {
    const wfId = selectedItem?.workflow_id || currentWfData?.workflow?.workflow_id
    if (!wfId) return
    setLoadingDetails(true)
    setError(null)
    try {
      await resumeWorkflow(wfId, org)
      const bundle = await getWorkflowEvidence(wfId, org)
      setCurrentWfData(bundle)
      updateWorkflow(bundle.workflow, bundle.evidence)
      await refreshReviewQueue()
      setSuccessMsg(`Workflow ${wfId} resumed successfully. Status: ${bundle.workflow?.status}.`)
    } catch (err) {
      setError(err)
      throw err
    } finally {
      setLoadingDetails(false)
    }
  }

  const workflow = currentWfData?.workflow
  const evidenceBundle = currentWfData?.evidence || {}
  const targetRecord = selectedItem?.record_id ? evidenceBundle[selectedItem.record_id] : null

  return (
    <div className={`w-full ${className}`}>
      {/* 1. Header Band */}
      <Band
        color="cream"
        title="Review Queue"
        description="Units where an agent returned UNCERTAIN or requested human review (needs_human: true). Record who decided and why, keeping the original evidence immutable."
      >
        {/* Error notification */}
        {error && (
          <ErrorBanner
            error={error}
            onDismiss={() => setError(null)}
            title="Review Queue Action Failed"
          />
        )}

        {/* Success notification */}
        {successMsg && (
          <div className="card-signature p-4 my-4 bg-emerald-50 border-2 border-emerald-600 text-emerald-950 flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-sm">
              <CheckCircle2 size={18} className="text-emerald-700" />
              <span>{successMsg}</span>
            </div>
            <button
              type="button"
              onClick={() => setSuccessMsg('')}
              className="text-xs font-mono font-semibold underline text-emerald-800"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* 2. Queue Controls: Tabs, Refresh & Lookup */}
        <div className="card-signature p-4 sm:p-6 bg-card mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-rule pb-4 mb-4">
            {/* Tabs: Pending vs Resolved */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setActiveTab('pending')}
                className={`px-4 py-2 rounded-xl border-2 font-bold text-xs sm:text-sm min-h-[44px] flex items-center gap-2 transition-all focus:outline-none focus-visible:ring-2 ${
                  activeTab === 'pending'
                    ? 'bg-mustard text-ink border-ink shadow-[2px_2px_0_var(--ink)] -translate-y-0.5'
                    : 'bg-white text-muted border-ink/30 hover:border-ink hover:text-ink'
                }`}
              >
                <ClipboardList size={16} />
                <span>Pending Review</span>
                <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-[#D64545] text-white">
                  {pendingCount}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setActiveTab('resolved')}
                className={`px-4 py-2 rounded-xl border-2 font-bold text-xs sm:text-sm min-h-[44px] flex items-center gap-2 transition-all focus:outline-none focus-visible:ring-2 ${
                  activeTab === 'resolved'
                    ? 'bg-mustard text-ink border-ink shadow-[2px_2px_0_var(--ink)] -translate-y-0.5'
                    : 'bg-white text-muted border-ink/30 hover:border-ink hover:text-ink'
                }`}
              >
                <CheckCheck size={16} />
                <span>Resolved</span>
                <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-stone-200 text-ink">
                  {resolvedCount}
                </span>
              </button>
            </div>

            {/* Refresh and Search Controls */}
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => refreshReviewQueue()}
                disabled={reviewLoading}
                className="btn-secondary text-xs py-2 px-3 min-h-[44px] inline-flex items-center gap-1.5"
                title="Refresh Review Queue"
              >
                <RefreshCw size={14} className={reviewLoading ? 'animate-spin' : ''} />
                <span className="hidden xs:inline">Refresh</span>
              </button>

              <form onSubmit={handleCustomSearch} className="flex items-center gap-1.5 flex-1 sm:flex-initial">
                <input
                  type="text"
                  value={customWfId}
                  onChange={(e) => setCustomWfId(e.target.value)}
                  placeholder="Lookup WF-ID..."
                  className="w-full sm:w-44 px-3 py-2 border-2 border-ink rounded-xl font-mono text-base md:text-xs bg-white focus:outline-none min-h-[44px]"
                />
                <button type="submit" className="btn-primary text-xs py-2 px-3 min-h-[44px]">
                  <Search size={14} />
                  <span>Fetch</span>
                </button>
              </form>
            </div>
          </div>

          {/* Tenant scoping note */}
          <div className="flex items-center justify-between text-xs text-muted">
            <span>
              Organisation: <strong className="font-mono text-ink">{org}</strong>
            </span>
            <span>
              {displayedItems.length} {activeTab === 'pending' ? 'pending item(s)' : 'resolved item(s)'}
            </span>
          </div>
        </div>

        {/* 3. Queue Item Cards Grid */}
        <div className="space-y-4 mb-8">
          <h4 className="font-serif text-lg font-bold text-ink flex items-center justify-between">
            <span>{activeTab === 'pending' ? 'Pending Review Items' : 'Resolved Overrides History'}</span>
            <span className="text-xs font-mono font-normal text-muted">
              Active Tenant: {org}
            </span>
          </h4>

          {displayedItems.length === 0 ? (
            <div className="card-signature p-10 text-center bg-card border-2 border-dashed border-ink/30 space-y-3">
              <ClipboardList size={32} className="mx-auto text-muted/60" />
              <div className="font-serif font-bold text-base text-ink">
                {activeTab === 'pending'
                  ? `No pending review items for ${org}`
                  : `No resolved overrides on record for ${org}`}
              </div>
              <p className="text-xs text-muted max-w-md mx-auto">
                {activeTab === 'pending'
                  ? 'All agent stages have passed or been resolved. Any stage returning UNCERTAIN or requiring human decision will appear here.'
                  : 'Overrides recorded by operators will be catalogued here alongside their original immutable evidence.'}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
              {displayedItems.map((item) => {
                const isSelected =
                  (selectedItem?.record_id && selectedItem.record_id === item.record_id) ||
                  (selectedItem?.workflow_id && selectedItem.workflow_id === item.workflow_id)

                return (
                  <div
                    key={item.id || item.record_id}
                    onClick={() => loadItemDetails(item)}
                    className={`p-4 rounded-xl border-2 transition-all cursor-pointer flex flex-col justify-between space-y-3 text-left focus:outline-none ${
                      isSelected
                        ? 'border-ink bg-peach shadow-[4px_4px_0_var(--ink)] -translate-y-0.5'
                        : 'border-ink/40 bg-white hover:border-ink hover:bg-stone-50/80 shadow-xs'
                    }`}
                  >
                    {/* Card Top: Stage Badge, Ad-Hoc Tag, Verdict */}
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="font-mono text-xs font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-stone-200 text-ink border border-ink/20">
                          {item.stage}
                        </span>
                        {item.is_ad_hoc_upload && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-amber-100 text-amber-900 border border-amber-300">
                            <Upload size={10} />
                            <span>ad hoc upload</span>
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-1.5">
                        <VerdictBadge verdict={item.effective_verdict || item.verdict} size="sm" />
                      </div>
                    </div>

                    {/* Unit ID and Reason */}
                    <div>
                      <div className="text-xs text-muted uppercase font-bold tracking-wider mb-0.5">
                        Unit Reference
                      </div>
                      <div className="font-mono font-bold text-base text-ink break-anywhere">
                        {item.unit_id}
                      </div>
                      <div className="text-xs text-stone-700 line-clamp-2 mt-1.5 leading-relaxed">
                        {item.reason}
                      </div>
                    </div>

                    {/* Record ID and Action Footer */}
                    <div className="pt-2 border-t border-ink/15 flex items-center justify-between gap-2 text-xs">
                      <div className="min-w-0">
                        <span className="text-[10px] font-mono text-muted block">Evidence Record:</span>
                        <span className="font-mono font-semibold text-ink text-[11px] truncate block max-w-[170px]" title={item.record_id}>
                          {item.record_id}
                        </span>
                      </div>

                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          loadItemDetails(item)
                        }}
                        className="btn-primary text-xs py-1.5 px-3 shrink-0 flex items-center gap-1 min-h-[36px]"
                      >
                        <span>{item.status === 'resolved' ? 'View' : 'Decide'}</span>
                        <ArrowRight size={13} />
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* 4. Loaded Workflow & Override Inspection Workspace */}
        {loadingDetails && !workflow && (
          <div className="card-signature p-12 text-center bg-card flex flex-col items-center justify-center gap-3">
            <div className="w-10 h-10 rounded-full border-4 border-ink border-t-mustard animate-spin" />
            <span className="font-serif text-lg font-bold text-ink">
              Loading Workflow Dossier & Evidence...
            </span>
          </div>
        )}

        {workflow && (
          <div className="space-y-6 pt-4 border-t-2 border-ink">
            {/* Active Workflow Banner */}
            <div className="card-highlight p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <span className="text-xs uppercase font-bold tracking-wider text-ink/70">
                  Dossier Under Review
                </span>
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-mono text-xl md:text-2xl font-bold text-ink break-anywhere">
                    {workflow.workflow_id}
                  </h3>
                  {workflow.is_ad_hoc_upload && (
                    <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-amber-200 text-amber-950 border border-amber-400">
                      Ad Hoc Upload
                    </span>
                  )}
                </div>
                <p className="text-xs text-ink/80 mt-1">
                  Status: <strong>{workflow.status}</strong> &bull; Reason: {workflow.status_reason || selectedItem?.reason || '—'}
                </p>
              </div>

              <div className="flex items-center gap-3 self-start sm:self-center">
                <VerdictBadge
                  verdict={workflow.final_outcome?.verdict || selectedItem?.effective_verdict || 'UNCERTAIN'}
                  size="md"
                />
                {workflow.final_outcome?.outcome && (
                  <span className="font-mono text-xs font-bold px-2.5 py-1 rounded-lg border-2 border-ink bg-card text-ink shadow-xs">
                    {workflow.final_outcome.outcome}
                  </span>
                )}
              </div>
            </div>

            {/* Target Evidence Record Panel (if selected) */}
            {targetRecord && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="font-serif text-base font-bold text-ink flex items-center gap-2">
                    <ClipboardList size={18} />
                    <span>Evidence Record Under Inspection ({targetRecord.record_id})</span>
                  </h4>
                </div>
                <EvidenceRecordPanel evidence={targetRecord} />
              </div>
            )}

            {/* Override Panel Form and Audit Log */}
            <OverridePanel
              workflow={workflow}
              evidence={evidenceBundle}
              initialActor={operator}
              onSubmitOverride={handleOverrideSubmit}
              onResumeWorkflow={handleResume}
              loading={loadingDetails}
            />
          </div>
        )}
      </Band>
    </div>
  )
}
