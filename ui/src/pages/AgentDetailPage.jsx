import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useSession } from '../context/SessionContext'
import Band from '../components/Band'
import CheckTable from '../components/CheckTable'
import VerdictBadge from '../components/VerdictBadge'
import ErrorBanner from '../components/ErrorBanner'
import { AGENTS } from '../data/agents'
import { createWorkflow, getWorkflowEvidence } from '../api/client'
import { formatCurrency, formatTimestamp, truncateHash } from '../lib/format'
import {
  Play,
  Upload,
  Search,
  ArrowLeft,
  ArrowRight,
  AlertTriangle,
  CheckCircle2,
  FileText,
  Image as ImageIcon,
  X,
  ShieldAlert,
  Info,
  Layers,
} from 'lucide-react'

export default function AgentDetailPage() {
  const { stage } = useParams()
  const { org, sessionWorkflows, recentEvidenceByStage, recordWorkflowRun } = useSession()

  const agent = AGENTS.find((a) => a.stage === stage)

  // Order Details Form State
  const [unitId, setUnitId] = useState('UNIT-0011')
  const [route, setRoute] = useState('auto')
  const [returned, setReturned] = useState('auto')

  // Discovered Order Lines / SKUs from runs
  const [discoveredRefs, setDiscoveredRefs] = useState(null)

  // Local image previews (never sent to API)
  const [uploadedImages, setUploadedImages] = useState([])

  // Execution State for "Check"
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [checkResult, setCheckResult] = useState(null)

  // Evidence Search State
  const [searchWfId, setSearchWfId] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchResult, setSearchResult] = useState(null)
  const [searchError, setSearchError] = useState(null)

  // Clear all displayed workflow results and evidence when tenant org changes
  useEffect(() => {
    setCheckResult(null)
    setError(null)
    setSearchResult(null)
    setSearchError(null)
    setDiscoveredRefs(null)
  }, [org])

  if (!agent) {
    return (
      <Band color="cream" className="py-16">
        <div className="card-signature p-8 bg-card text-center max-w-lg mx-auto">
          <h2 className="font-serif text-2xl font-bold text-ink mb-2">
            Unknown Agent Stage
          </h2>
          <p className="text-sm text-muted mb-4">
            No agent found for stage '{stage}'.
          </p>
          <Link to="/app/dashboard" className="btn-secondary text-sm py-2 px-4 inline-flex items-center gap-2">
            <ArrowLeft size={16} />
            <span>Back to Dashboard</span>
          </Link>
        </div>
      </Band>
    )
  }

  // Handle local image file selection
  const handleImageChange = (e) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return

    const newPreviews = files.map((file) => ({
      name: file.name,
      size: (file.size / 1024).toFixed(1) + ' KB',
      url: URL.createObjectURL(file),
    }))

    setUploadedImages((prev) => [...prev, ...newPreviews])
  }

  const handleRemoveImage = (index) => {
    setUploadedImages((prev) => prev.filter((_, i) => i !== index))
  }

  // Execute "Check" via orchestrator POST /workflows
  const handleRunCheck = async (e) => {
    e.preventDefault()
    if (!unitId.trim()) return

    setLoading(true)
    setError(null)
    setCheckResult(null)

    try {
      const payload = {
        org_id: org,
        unit_id: unitId.trim(),
        route: route !== 'auto' ? route : undefined,
        returned: returned === 'auto' ? undefined : returned === 'true',
      }

      const runWf = await createWorkflow(payload)

      // Fetch full evidence bundle for stage details
      let bundle = { workflow: runWf, evidence: {} }
      if (runWf?.workflow_id) {
        try {
          bundle = await getWorkflowEvidence(runWf.workflow_id)
        } catch (evErr) {
          console.warn('Could not fetch evidence bundle:', evErr)
        }
      }

      const finalWf = bundle.workflow || runWf
      const evidenceMap = bundle.evidence || {}

      // Record run in session context
      recordWorkflowRun(finalWf, evidenceMap)

      // Extract discovered order lines / SKUs if available
      let refsFound = null
      Object.values(evidenceMap).forEach((ev) => {
        if (ev?.subject?.refs && Object.keys(ev.subject.refs).length > 0) {
          refsFound = { ...refsFound, ...ev.subject.refs }
        }
      })
      if (refsFound) {
        setDiscoveredRefs(refsFound)
      }

      // Extract THIS agent's stage result only
      const stageResults = finalWf.stage_results || []
      const stageRes = stageResults.find((sr) => sr.stage === stage)
      const stageEv = stageRes?.record_id ? evidenceMap[stageRes.record_id] : null

      setCheckResult({
        workflow: finalWf,
        stageResult: stageRes,
        evidence: stageEv,
      })
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }

  // Evidence Search by workflow_id
  const handleSearchEvidence = async (e) => {
    e.preventDefault()
    if (!searchWfId.trim()) return

    setSearching(true)
    setSearchError(null)
    setSearchResult(null)

    try {
      const bundle = await getWorkflowEvidence(searchWfId.trim())
      const wf = bundle.workflow
      const allEvidence = bundle.evidence || {}

      // Tenancy check: refuse if workflow belongs to another organisation
      if (wf && wf.org_id !== org) {
        setSearchError({
          status: 403,
          message: `Cross-Tenant Access Refused: workflow ${searchWfId} belongs to ${wf.org_id}, not active tenant ${org}.`,
        })
        return
      }

      // Filter evidence for THIS agent's stage only
      const matching = Object.values(allEvidence).filter((ev) => ev.stage === stage)

      setSearchResult({
        workflow: wf,
        records: matching,
      })
    } catch (err) {
      setSearchError(err)
    } finally {
      setSearching(false)
    }
  }

  // Session evidence for this stage
  const sessionEvidence = checkResult?.evidence || recentEvidenceByStage[stage] || null

  return (
    <div className="w-full space-y-0">
      {/* 1. Header: Agent Name, Short Description, When It Runs */}
      <Band
        color="cream"
        badge={
          <Link
            to="/app/dashboard"
            className="inline-flex items-center gap-1.5 text-xs font-bold text-muted hover:text-ink mb-2 focus:outline-none focus-visible:ring-2 rounded-lg"
          >
            <ArrowLeft size={14} />
            <span>Dashboard</span>
          </Link>
        }
        title={agent.name}
        description={agent.purpose}
      >
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <div className="px-3 py-1.5 rounded-xl border border-ink/30 bg-card font-medium text-ink">
            <span className="font-bold text-muted uppercase text-[10px] tracking-wider mr-1.5">When it runs:</span>
            <span>{agent.when}</span>
          </div>
          <div className="px-3 py-1.5 rounded-xl border border-ink/30 bg-card font-medium text-ink">
            <span className="font-bold text-muted uppercase text-[10px] tracking-wider mr-1.5">Applies to:</span>
            <span>{agent.routeApplies}</span>
          </div>
        </div>
      </Band>

      {/* 2. Order Details Form, Image Upload & Check Execution */}
      <Band color="teal">
        <div className="space-y-6">
          {/* Order Details Form Card */}
          <div className="card-signature p-6 md:p-8 bg-card">
            <h3 className="font-serif text-2xl font-bold text-ink mb-2">
              Order Details & Inspection
            </h3>
            <p className="text-xs text-muted mb-6">
              Configure inventory unit parameters. The tenant organisation ({org}) is set authoritatively by your session.
            </p>

            <form onSubmit={handleRunCheck} className="space-y-6">
              {/* Form Fields: unit_id, route, returned */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label htmlFor="agent-unit-id" className="block text-xs font-bold uppercase tracking-wider text-ink mb-1.5">
                    Unit ID (subject_id) *
                  </label>
                  <input
                    id="agent-unit-id"
                    type="text"
                    required
                    value={unitId}
                    onChange={(e) => setUnitId(e.target.value)}
                    placeholder="e.g. UNIT-0011"
                    className="w-full px-3.5 py-2.5 border-2 border-ink rounded-xl font-mono text-sm bg-white focus:outline-none"
                  />
                  <span className="text-[11px] text-muted block mt-1">
                    Canonical inventory unit reference
                  </span>
                </div>

                <div>
                  <label htmlFor="agent-route" className="block text-xs font-bold uppercase tracking-wider text-ink mb-1.5">
                    Route
                  </label>
                  <select
                    id="agent-route"
                    value={route}
                    onChange={(e) => setRoute(e.target.value)}
                    className="w-full px-3.5 py-2.5 border-2 border-ink rounded-xl text-sm bg-white focus:outline-none cursor-pointer"
                  >
                    <option value="auto">Auto-detect from manifest</option>
                    <option value="fba">FBA (Fulfillment by Amazon)</option>
                    <option value="mfn">MFN (Merchant-Fulfilled Network)</option>
                  </select>
                  <span className="text-[11px] text-muted block mt-1">
                    Directs stage routing (Prep vs Pack)
                  </span>
                </div>

                <div>
                  <label htmlFor="agent-returned" className="block text-xs font-bold uppercase tracking-wider text-ink mb-1.5">
                    Returned
                  </label>
                  <select
                    id="agent-returned"
                    value={returned}
                    onChange={(e) => setReturned(e.target.value)}
                    className="w-full px-3.5 py-2.5 border-2 border-ink rounded-xl text-sm bg-white focus:outline-none cursor-pointer"
                  >
                    <option value="auto">Auto-detect from case data</option>
                    <option value="false">No (returned=false)</option>
                    <option value="true">Yes (returned=true)</option>
                  </select>
                  <span className="text-[11px] text-muted block mt-1">
                    Enables Returns Manager stage if true
                  </span>
                </div>
              </div>

              {/* Read-only Display of Order Lines / SKUs */}
              <div className="p-4 rounded-xl border border-ink/20 bg-stone-50">
                <span className="text-xs font-bold uppercase tracking-wider text-muted block mb-2">
                  Order Lines & SKU Manifest (Read-Only)
                </span>
                {discoveredRefs ? (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
                    {discoveredRefs.sku && (
                      <div>
                        <span className="text-muted block text-[10px]">SKU:</span>
                        <strong className="text-ink">{discoveredRefs.sku}</strong>
                      </div>
                    )}
                    {discoveredRefs.asin && (
                      <div>
                        <span className="text-muted block text-[10px]">ASIN:</span>
                        <strong className="text-ink">{discoveredRefs.asin}</strong>
                      </div>
                    )}
                    {(discoveredRefs.po_number || discoveredRefs.order_id) && (
                      <div>
                        <span className="text-muted block text-[10px]">PO / Order:</span>
                        <strong className="text-ink">{discoveredRefs.po_number || discoveredRefs.order_id}</strong>
                      </div>
                    )}
                    {discoveredRefs.po_line && (
                      <div>
                        <span className="text-muted block text-[10px]">PO Line:</span>
                        <strong className="text-ink">{discoveredRefs.po_line}</strong>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-muted italic">
                    Order lines and SKUs will appear here after running a check on this unit.
                  </p>
                )}
              </div>

              {/* Image Upload Area with VISIBLE PREVIEW-ONLY DISCLAIMER */}
              <div className="p-4 rounded-xl border-2 border-dashed border-ink/30 bg-cream/30 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <ImageIcon size={18} className="text-ink" />
                    <span className="text-xs font-bold uppercase tracking-wider text-ink">
                      Visual Reference Upload
                    </span>
                  </div>

                  <label className="btn-secondary text-xs py-1.5 px-3 cursor-pointer inline-flex items-center gap-1.5">
                    <Upload size={14} />
                    <span>Choose Images</span>
                    <input
                      type="file"
                      multiple
                      accept="image/*"
                      onChange={handleImageChange}
                      className="hidden"
                    />
                  </label>
                </div>

                {/* Mandatory Disclaimer Label */}
                <div className="p-3 rounded-lg border border-amber-600/30 bg-amber-50/80 text-xs text-amber-900 flex items-start gap-2">
                  <Info size={16} className="shrink-0 text-amber-700 mt-0.5" />
                  <p className="leading-relaxed font-medium">
                    Preview only. Images are not sent to the agent: the orchestrator uses the captures it already holds for the unit.
                  </p>
                </div>

                {/* Thumbnail Previews */}
                {uploadedImages.length > 0 && (
                  <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-3 pt-2">
                    {uploadedImages.map((img, idx) => (
                      <div key={idx} className="relative group rounded-lg overflow-hidden border border-ink/30 bg-white">
                        <img src={img.url} alt={img.name} className="w-full h-20 object-cover" />
                        <div className="p-1 text-[10px] truncate font-mono text-muted bg-stone-50 border-t border-ink/10">
                          {img.name}
                        </div>
                        <button
                          type="button"
                          onClick={() => handleRemoveImage(idx)}
                          className="absolute top-1 right-1 p-0.5 rounded-full bg-ink text-white opacity-0 group-hover:opacity-100 transition-opacity"
                          aria-label="Remove image"
                        >
                          <X size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Submit "Check" Button */}
              <div className="pt-2 flex items-center justify-between gap-4">
                <div className="text-xs text-muted">
                  Active Tenant: <strong className="font-mono text-ink">{org}</strong>
                </div>

                <button
                  type="submit"
                  disabled={loading || !unitId.trim()}
                  className="btn-primary text-base py-3 px-8 flex items-center gap-2"
                >
                  <Play size={18} className="fill-ink" />
                  <span>{loading ? 'Running Pipeline...' : `Check ${agent.name}`}</span>
                </button>
              </div>
            </form>
          </div>

          {/* Error Banner / Wrong-Tenant Refusal */}
          {error && (
            <ErrorBanner
              error={error}
              onDismiss={() => setError(null)}
              title={error.status === 404 ? 'Cross-Tenant Request Refused' : 'Stage Error'}
            />
          )}

          {/* Stage Result: SHOWS ONLY THIS AGENT'S RESULT */}
          {checkResult && (
            <div className="card-signature p-6 md:p-8 bg-card space-y-6">
              <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b-2 border-ink/15">
                <div>
                  <span className="font-mono text-xs font-bold uppercase tracking-wider text-muted block mb-1">
                    Stage Result: {agent.name}
                  </span>
                  <h3 className="font-serif text-2xl font-bold text-ink">
                    {checkResult.stageResult?.state === 'skipped'
                      ? 'Stage Skipped'
                      : checkResult.stageResult?.state === 'error'
                      ? 'Stage Error'
                      : `Verdict: ${checkResult.stageResult?.verdict || 'N/A'}`}
                  </h3>
                </div>

                {checkResult.stageResult?.state === 'skipped' ? (
                  <VerdictBadge verdict="SKIPPED" size="lg" />
                ) : checkResult.stageResult?.state === 'error' ? (
                  <VerdictBadge verdict="FAIL" size="lg" />
                ) : (
                  <VerdictBadge verdict={checkResult.stageResult?.verdict} size="lg" />
                )}
              </div>

              {/* 7e: If Stage was Skipped, show recorded skip reason */}
              {checkResult.stageResult?.state === 'skipped' && (
                <div className="p-4 rounded-xl border-2 border-ink/30 bg-stone-100 text-sm space-y-2">
                  <div className="font-bold text-ink">
                    Reason for Skipping:
                  </div>
                  <div className="font-mono text-xs p-3 rounded-lg bg-white border border-ink/20 text-muted">
                    {checkResult.stageResult.skipped_reason || 'Routing conditions not met for this unit.'}
                  </div>
                  <p className="text-xs text-muted">
                    This unit’s fulfillment route or return status directed the orchestrator to bypass this stage.
                  </p>
                </div>
              )}

              {/* 7f: If Stage Errored, show recorded error code */}
              {checkResult.stageResult?.state === 'error' && (
                <div className="p-4 rounded-xl border-2 border-[#D64545] bg-[#D64545]/10 text-sm space-y-3">
                  <div className="flex items-center gap-2 font-bold text-[#A02222]">
                    <ShieldAlert size={18} />
                    <span>
                      {checkResult.stageResult.error?.message?.includes('in org_') ||
                      checkResult.stageResult.error?.code === 'tenant_mismatch'
                        ? 'Cross-Tenant Request Refused'
                        : 'Recorded Stage Error'}
                    </span>
                  </div>

                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-bold uppercase tracking-wider text-muted">Error Code:</span>
                      <span className="font-mono font-bold px-2 py-0.5 rounded bg-white border border-[#D64545]/40 text-[#A02222]">
                        {checkResult.stageResult.error?.code || 'stage_error'}
                      </span>
                    </div>

                    {checkResult.stageResult.error?.message && (
                      <div className="font-mono text-xs p-3 rounded-lg bg-white border border-[#D64545]/40 text-[#A02222]">
                        {checkResult.stageResult.error.message}
                      </div>
                    )}
                  </div>

                  <p className="text-xs text-stone-700">
                    This unit request was rejected by the stage agent. Tenant isolation prevents accessing records belonging to another organisation.
                  </p>
                </div>
              )}

              {/* 7d: Completed Stage Checks Table & Outcome */}
              {checkResult.stageResult?.state === 'completed' && (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="p-3 rounded-xl border border-ink/20 bg-stone-50">
                      <span className="text-[10px] uppercase font-bold text-muted block mb-0.5">Stage State</span>
                      <strong className="text-sm font-mono text-ink capitalize">{checkResult.stageResult.state}</strong>
                    </div>
                    <div className="p-3 rounded-xl border border-ink/20 bg-stone-50">
                      <span className="text-[10px] uppercase font-bold text-muted block mb-0.5">Stage Outcome</span>
                      <strong className="text-sm font-mono text-ink">{checkResult.stageResult.outcome || 'N/A'}</strong>
                    </div>
                    <div className="p-3 rounded-xl border border-ink/20 bg-stone-50">
                      <span className="text-[10px] uppercase font-bold text-muted block mb-0.5">Record ID</span>
                      <strong className="text-sm font-mono text-ink">{checkResult.stageResult.record_id || 'N/A'}</strong>
                    </div>
                    <div className="p-3 rounded-xl border border-ink/20 bg-stone-50">
                      <span className="text-[10px] uppercase font-bold text-muted block mb-0.5">Duration</span>
                      <strong className="text-sm font-mono text-ink">{checkResult.stageResult.duration_ms ? `${checkResult.stageResult.duration_ms}ms` : 'N/A'}</strong>
                    </div>
                  </div>

                  {/* Individual Checks Table with Verdict, Confidence & Uncertain Reason */}
                  <div>
                    <h4 className="text-xs font-bold uppercase tracking-wider text-muted mb-2">
                      Stage Verification Checks ({checkResult.evidence?.checks?.length || 0})
                    </h4>
                    {checkResult.evidence?.checks?.length > 0 ? (
                      <CheckTable checks={checkResult.evidence.checks} />
                    ) : (
                      <p className="text-xs text-muted italic">
                        No individual check array reported for this stage record.
                      </p>
                    )}
                  </div>
                </div>
              )}

              {/* 7g: Link to Review Queue if UNCERTAIN or BLOCKED */}
              {(checkResult.stageResult?.verdict === 'UNCERTAIN' ||
                checkResult.workflow?.status === 'BLOCKED' ||
                checkResult.stageResult?.needs_human) && (
                <div className="p-4 rounded-xl border-2 border-[#E39A0B] bg-[#E39A0B]/15 flex flex-col sm:flex-row items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <AlertTriangle size={24} className="text-[#9A6202] shrink-0" />
                    <div>
                      <strong className="text-sm font-bold text-[#9A6202] block">
                        Requires Human Review
                      </strong>
                      <span className="text-xs text-stone-800">
                        {checkResult.stageResult?.uncertain_reason ||
                          'This stage returned an UNCERTAIN verdict requiring manual inspection and decision.'}
                      </span>
                    </div>
                  </div>

                  <Link
                    to="/app/review"
                    className="btn-primary text-xs py-2.5 px-4 shrink-0 flex items-center gap-1.5"
                  >
                    <span>Open Review Queue</span>
                    <ArrowRight size={14} />
                  </Link>
                </div>
              )}
            </div>
          )}
        </div>
      </Band>

      {/* 8. Evidence Record Section for This Agent */}
      <Band color="charcoal">
        <div className="space-y-8">
          <div>
            <span className="text-xs font-mono uppercase tracking-wider text-mustard block mb-1">
              Audit & Traceability
            </span>
            <h3 className="font-serif text-3xl font-bold text-cream">
              Evidence Record: {agent.name}
            </h3>
            <p className="text-xs text-[#D1CBBF] mt-1">
              Immutable cryptographic evidence records generated for this stage.
            </p>
          </div>

          {/* 8a: Most Recent Session Evidence Record */}
          <div className="card-signature p-6 bg-card text-ink">
            <h4 className="font-serif text-xl font-bold text-ink mb-4 flex items-center gap-2">
              <FileText size={18} className="text-muted" />
              <span>Most Recent Session Record ({stage})</span>
            </h4>

            {sessionEvidence ? (
              <div className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-mono">
                  <div className="p-3 rounded-lg border border-ink/20 bg-stone-50">
                    <span className="text-muted block text-[10px]">Record ID:</span>
                    <strong className="text-ink text-sm">{sessionEvidence.record_id}</strong>
                  </div>
                  <div className="p-3 rounded-lg border border-ink/20 bg-stone-50">
                    <span className="text-muted block text-[10px]">Content Hash (SHA-256):</span>
                    <strong className="text-ink text-xs truncate block" title={sessionEvidence.content_hash}>
                      {truncateHash(sessionEvidence.content_hash, 16)}
                    </strong>
                  </div>
                  <div className="p-3 rounded-lg border border-ink/20 bg-stone-50">
                    <span className="text-muted block text-[10px]">Upstream References:</span>
                    <strong className="text-ink text-xs">
                      {sessionEvidence.upstream_refs?.length > 0
                        ? sessionEvidence.upstream_refs.join(', ')
                        : 'None (Root)'}
                    </strong>
                  </div>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
                  <div>
                    <span className="text-muted block text-[10px] font-bold uppercase">Verdict:</span>
                    <div className="mt-1">
                      <VerdictBadge verdict={sessionEvidence.decision?.verdict} size="sm" />
                    </div>
                  </div>
                  <div>
                    <span className="text-muted block text-[10px] font-bold uppercase">Confidence:</span>
                    <span className="font-mono font-bold text-ink">
                      {sessionEvidence.decision?.confidence !== null && sessionEvidence.decision?.confidence !== undefined
                        ? sessionEvidence.decision.confidence
                        : 'N/A'}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted block text-[10px] font-bold uppercase">Model Name:</span>
                    <span className="font-mono text-ink">
                      {sessionEvidence.model?.name || 'csv-replay-stub'}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted block text-[10px] font-bold uppercase">Model Calls / Cost:</span>
                    <span className="font-mono text-ink">
                      {sessionEvidence.model?.calls ?? 0} calls ({formatCurrency(sessionEvidence.model?.cost_usd || 0)})
                    </span>
                  </div>
                </div>

                {sessionEvidence.checks?.length > 0 && (
                  <div className="pt-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-muted block mb-2">
                      Checks Evaluated
                    </span>
                    <CheckTable checks={sessionEvidence.checks} />
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-muted italic">
                No evidence recorded for this stage in the current session yet. Run a check above to produce a record.
              </p>
            )}
          </div>

          {/* 8b: Search Box for Specific Workflow Evidence */}
          <div className="card-signature p-6 bg-card text-ink">
            <h4 className="font-serif text-xl font-bold text-ink mb-2">
              Query Historical Workflow Evidence
            </h4>
            <p className="text-xs text-muted mb-4">
              Inspect past evidence for the {agent.name} stage from any recorded workflow ID.
            </p>

            <form onSubmit={handleSearchEvidence} className="flex flex-col sm:flex-row gap-3 mb-6">
              <input
                type="text"
                required
                value={searchWfId}
                onChange={(e) => setSearchWfId(e.target.value)}
                placeholder="e.g. WF-org_demo_alpha-UNIT-0014"
                className="flex-1 px-4 py-2.5 border-2 border-ink rounded-xl font-mono text-sm bg-white focus:outline-none"
              />
              <button
                type="submit"
                disabled={searching || !searchWfId.trim()}
                className="btn-primary text-sm py-2.5 px-6 shrink-0 flex items-center justify-center gap-1.5"
              >
                <Search size={16} />
                <span>{searching ? 'Searching...' : 'Search'}</span>
              </button>
            </form>

            {/* Search Refusal / Error */}
            {searchError && (
              <ErrorBanner
                error={searchError}
                onDismiss={() => setSearchError(null)}
                title={searchError.status === 403 ? 'Cross-Tenant Refusal' : 'Workflow Not Found'}
              />
            )}

            {/* Search Results: THIS AGENT'S STAGE ONLY */}
            {searchResult && (
              <div className="space-y-4 pt-2 border-t border-ink/15">
                <div className="flex items-center justify-between text-xs text-muted">
                  <span>Workflow: <strong className="font-mono text-ink">{searchResult.workflow?.workflow_id}</strong></span>
                  <span>Tenant: <strong className="font-mono text-ink">{searchResult.workflow?.org_id}</strong></span>
                </div>

                {searchResult.records.length > 0 ? (
                  searchResult.records.map((rec) => (
                    <div key={rec.record_id} className="p-4 rounded-xl border-2 border-ink bg-stone-50 space-y-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="font-mono text-sm font-bold text-ink">
                          Record ID: {rec.record_id}
                        </div>
                        <VerdictBadge verdict={rec.decision?.verdict} size="sm" />
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs font-mono text-muted">
                        <div>Hash: <span className="text-ink">{truncateHash(rec.content_hash, 16)}</span></div>
                        <div>Upstream: <span className="text-ink">{rec.upstream_refs?.join(', ') || 'Root'}</span></div>
                        <div>Confidence: <span className="text-ink">{rec.decision?.confidence ?? 'N/A'}</span></div>
                      </div>

                      {rec.checks?.length > 0 && (
                        <div>
                          <CheckTable checks={rec.checks} />
                        </div>
                      )}
                    </div>
                  ))
                ) : (
                  <div className="p-4 rounded-xl border border-ink/20 bg-stone-100 text-xs text-muted text-center font-medium">
                    No evidence found for this stage in that workflow.
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </Band>
    </div>
  )
}
