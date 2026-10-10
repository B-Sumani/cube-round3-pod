import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useSession } from '../context/SessionContext'
import Band from '../components/Band'
import CheckTable from '../components/CheckTable'
import VerdictBadge from '../components/VerdictBadge'
import ErrorBanner from '../components/ErrorBanner'
import { AGENTS } from '../data/agents'
import { createWorkflow, getWorkflowEvidence, getCatalogue, runStageUpload } from '../api/client'
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
  Package,
  Barcode,
  Plus,
  Minus,
  Loader2,
} from 'lucide-react'

// Client-side image resize & compression to under 3 MB (Vercel serverless limit)
async function compressImageFile(file, maxBytes = 3 * 1024 * 1024) {
  const allowed = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
  const ext = (file.name || '').split('.').pop().toLowerCase()
  if (!allowed.includes(file.type) && !['jpg', 'jpeg', 'png', 'webp'].includes(ext)) {
    throw new Error(`Unsupported file type: "${file.name}". Allowed formats: JPG, PNG, WebP.`)
  }

  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Failed to read image file.'))
    reader.onload = (event) => {
      const img = new Image()
      img.onerror = () => reject(new Error('Could not parse image. Please select a valid image.'))
      img.onload = () => {
        const canvas = document.createElement('canvas')
        let width = img.width
        let height = img.height
        const maxDim = 1920

        if (width > maxDim || height > maxDim) {
          if (width > height) {
            height = Math.round((height * maxDim) / width)
            width = maxDim
          } else {
            width = Math.round((width * maxDim) / height)
            height = maxDim
          }
        }

        canvas.width = width
        canvas.height = height
        const ctx = canvas.getContext('2d')
        ctx.drawImage(img, 0, 0, width, height)

        let quality = 0.90
        const exportMime = file.type === 'image/png' ? 'image/jpeg' : (file.type || 'image/jpeg')

        const tryBlob = (q) => {
          canvas.toBlob(
            (blob) => {
              if (!blob) {
                reject(new Error('Canvas image conversion failed.'))
                return
              }
              if (blob.size <= maxBytes || q <= 0.3) {
                if (blob.size > maxBytes) {
                  reject(new Error(`Image exceeds 3 MB limit even after compression (${(blob.size / (1024 * 1024)).toFixed(2)} MB). Please select a smaller photo.`))
                  return
                }
                const newExt = exportMime === 'image/webp' ? '.webp' : '.jpg'
                const outName = file.name.replace(/\.[^/.]+$/, '') + newExt
                const compressed = new File([blob], outName, {
                  type: exportMime,
                  lastModified: Date.now(),
                })
                resolve(compressed)
              } else {
                tryBlob(q - 0.15)
              }
            },
            exportMime,
            q
          )
        }

        tryBlob(quality)
      }
      img.src = event.target.result
    }
    reader.readAsDataURL(file)
  })
}

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

  // Local image previews & upload state
  const [uploadedImages, setUploadedImages] = useState([])
  const [selectedUploadFile, setSelectedUploadFile] = useState(null)
  const [uploadFilePreview, setUploadFilePreview] = useState(null)
  const [uploadCompressing, setUploadCompressing] = useState(false)
  const [uploadError, setUploadError] = useState(null)

  // Execution State for "Check"
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [checkResult, setCheckResult] = useState(null)

  // Evidence Search State
  const [searchWfId, setSearchWfId] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchResult, setSearchResult] = useState(null)
  const [searchError, setSearchError] = useState(null)

  // Catalogue & Order Builder State (Pack Manager)
  const [catalogue, setCatalogue] = useState([])
  const [catalogueLoading, setCatalogueLoading] = useState(false)
  const [catalogueError, setCatalogueError] = useState(null)
  const [catalogueSearch, setCatalogueSearch] = useState('')
  const [orderQuantities, setOrderQuantities] = useState({})

  // Fetch catalogue for Pack Manager
  useEffect(() => {
    if (stage === 'pack') {
      setCatalogueLoading(true)
      setCatalogueError(null)
      getCatalogue(org)
        .then((items) => {
          setCatalogue(Array.isArray(items) ? items : [])
        })
        .catch((err) => {
          console.warn('Catalogue load error:', err)
          setCatalogueError(err.message || 'Could not load catalogue')
        })
        .finally(() => {
          setCatalogueLoading(false)
        })
    }
  }, [stage, org])

  // Clear all displayed workflow results and evidence when tenant org changes
  useEffect(() => {
    setCheckResult(null)
    setError(null)
    setSearchResult(null)
    setSearchError(null)
    setDiscoveredRefs(null)
    setOrderQuantities({})
  }, [org])

  const updateQuantity = (sku, delta) => {
    setOrderQuantities((prev) => {
      const cur = prev[sku] || 0
      const next = Math.max(0, cur + delta)
      if (next === 0) {
        const copy = { ...prev }
        delete copy[sku]
        return copy
      }
      return { ...prev, [sku]: next }
    })
  }

  const clearOrderLines = () => {
    setOrderQuantities({})
  }

  const builtOrderLines = Object.entries(orderQuantities)
    .filter(([_, q]) => q > 0)
    .map(([s, q]) => `${s}:${q}`)
    .join(';')

  const filteredCatalogue = catalogue.filter((item) => {
    if (!catalogueSearch.trim()) return true
    const q = catalogueSearch.toLowerCase()
    return (
      (item.sku && item.sku.toLowerCase().includes(q)) ||
      (item.title && item.title.toLowerCase().includes(q)) ||
      (item.name && item.name.toLowerCase().includes(q)) ||
      (item.description && item.description.toLowerCase().includes(q)) ||
      (item.packaging_type && item.packaging_type.toLowerCase().includes(q)) ||
      (item.barcode && item.barcode.toLowerCase().includes(q))
    )
  })

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

  // Handle local image file selection and client-side compression
  const handleImageChange = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploadError(null)
    setUploadCompressing(true)

    try {
      const compressed = await compressImageFile(file)
      setSelectedUploadFile(compressed)
      const prevUrl = URL.createObjectURL(compressed)
      setUploadFilePreview({
        name: compressed.name,
        originalSize: (file.size / (1024 * 1024)).toFixed(2) + ' MB',
        compressedSize: (compressed.size / (1024 * 1024)).toFixed(2) + ' MB',
        url: prevUrl,
      })
    } catch (err) {
      setUploadError(err.message || 'Image processing failed')
      setSelectedUploadFile(null)
      setUploadFilePreview(null)
    } finally {
      setUploadCompressing(false)
    }
  }

  const handleClearUpload = () => {
    setSelectedUploadFile(null)
    setUploadFilePreview(null)
    setUploadError(null)
  }

  const handleRemoveImage = (index) => {
    setUploadedImages((prev) => prev.filter((_, i) => i !== index))
  }

  // Execute Agent on Uploaded Image via POST /stages/{stage}/run-upload
  const handleRunUpload = async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (!selectedUploadFile) return
    if (!unitId.trim()) return

    setLoading(true)
    setError(null)
    setUploadError(null)
    setCheckResult(null)

    try {
      const res = await runStageUpload({
        stage,
        file: selectedUploadFile,
        unit_id: unitId.trim(),
        org_id: org,
        order_lines: stage === 'pack' && builtOrderLines ? builtOrderLines : undefined,
        route: route !== 'auto' ? route : (stage === 'pack' ? 'mfn' : undefined),
      })

      if (res.workflow && res.evidence) {
        recordWorkflowRun(res.workflow, { [res.evidence.record_id]: res.evidence })
      }

      setCheckResult({
        workflow: res.workflow,
        stageResult: res.stage_result,
        evidence: res.evidence,
        isAdHocUpload: true,
        storageNote: res.storage_note,
      })
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
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
        route: route !== 'auto' ? route : (stage === 'pack' ? 'mfn' : undefined),
        returned: returned === 'auto' ? undefined : returned === 'true',
        order_lines: stage === 'pack' && builtOrderLines ? builtOrderLines : undefined,
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

              {/* Product Catalogue & Order Builder (Pack Manager) vs Read-only Display (Other stages) */}
              {stage === 'pack' ? (
                <div className="p-5 rounded-xl border-2 border-ink/30 bg-stone-50 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 mb-0.5">
                        <Package size={16} className="text-ink" />
                        <span className="font-mono text-xs font-bold uppercase tracking-wider text-muted">
                          Product Catalogue & Order Builder ({org})
                        </span>
                      </div>
                      <h4 className="font-serif text-lg font-bold text-ink">
                        Pick Order SKUs to Match Box Contents
                      </h4>
                    </div>

                    {/* Search Input */}
                    <div className="relative w-full sm:w-64">
                      <Search size={14} className="absolute left-3 top-2.5 text-muted pointer-events-none" />
                      <input
                        type="text"
                        value={catalogueSearch}
                        onChange={(e) => setCatalogueSearch(e.target.value)}
                        placeholder="Search SKU, name, barcode..."
                        className="w-full pl-8 pr-7 py-1.5 border border-ink/30 rounded-lg text-xs font-mono bg-white focus:outline-none"
                      />
                      {catalogueSearch && (
                        <button
                          type="button"
                          onClick={() => setCatalogueSearch('')}
                          className="absolute right-2 top-2 text-muted hover:text-ink text-xs"
                        >
                          <X size={12} />
                        </button>
                      )}
                    </div>
                  </div>

                  <p className="text-xs text-muted">
                    Build the expected order manifest from your seller catalogue. The Pack Manager checks the open carton photo against these items, verifying presence, counts, and flagging extra items.
                  </p>

                  {/* Catalogue Table */}
                  {catalogueLoading ? (
                    <div className="p-6 text-center text-xs text-muted font-mono">
                      Loading product catalogue for {org}...
                    </div>
                  ) : catalogueError ? (
                    <div className="p-3 rounded-lg border border-[#D64545]/30 bg-[#D64545]/10 text-xs text-[#A02222]">
                      {catalogueError}
                    </div>
                  ) : filteredCatalogue.length === 0 ? (
                    <div className="p-4 text-center text-xs text-muted italic">
                      No products found matching "{catalogueSearch}".
                    </div>
                  ) : (
                    <div className="overflow-x-auto border border-ink/20 rounded-xl bg-white max-h-72 overflow-y-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-stone-100 border-b border-ink/20 font-bold uppercase text-[10px] text-muted tracking-wider sticky top-0">
                          <tr>
                            <th className="py-2.5 px-3">SKU</th>
                            <th className="py-2.5 px-3">Product Name & Details</th>
                            <th className="py-2.5 px-3">Expected Packaging</th>
                            <th className="py-2.5 px-3">Barcode</th>
                            <th className="py-2.5 px-3">Hazmat</th>
                            <th className="py-2.5 px-3 text-right">Order Qty</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-ink/10 font-mono">
                          {filteredCatalogue.map((item) => {
                            const qty = orderQuantities[item.sku] || 0
                            return (
                              <tr key={item.sku} className={`hover:bg-cream/40 transition-colors ${qty > 0 ? 'bg-cream/20' : ''}`}>
                                <td className="py-2 px-3 font-bold text-ink whitespace-nowrap">
                                  {item.sku}
                                </td>
                                <td className="py-2 px-3 font-sans">
                                  <div className="font-bold text-ink">{item.title || item.name}</div>
                                  <div className="text-[11px] text-muted line-clamp-1">{item.description}</div>
                                </td>
                                <td className="py-2 px-3 whitespace-nowrap">
                                  <span className="px-2 py-0.5 rounded border border-ink/20 bg-stone-100 text-[10px] uppercase font-bold text-ink">
                                    {item.expected_packaging || item.packaging_type || 'standard'}
                                  </span>
                                </td>
                                <td className="py-2 px-3 text-muted text-[11px] whitespace-nowrap">
                                  {item.barcode || `BAR-${item.sku}`}
                                </td>
                                <td className="py-2 px-3 whitespace-nowrap">
                                  {item.hazmat ? (
                                    <span className="px-1.5 py-0.5 rounded bg-amber-100 border border-amber-300 text-amber-900 text-[10px] font-bold">
                                      HAZMAT
                                    </span>
                                  ) : (
                                    <span className="text-[10px] text-muted font-sans">No</span>
                                  )}
                                </td>
                                <td className="py-2 px-3 text-right whitespace-nowrap">
                                  <div className="inline-flex items-center gap-1.5">
                                    <button
                                      type="button"
                                      onClick={() => updateQuantity(item.sku, -1)}
                                      disabled={qty === 0}
                                      className="w-6 h-6 rounded border border-ink/30 bg-stone-50 hover:bg-stone-200 disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center font-bold text-ink"
                                    >
                                      -
                                    </button>
                                    <span className="w-6 text-center font-bold text-xs text-ink">{qty}</span>
                                    <button
                                      type="button"
                                      onClick={() => updateQuantity(item.sku, 1)}
                                      className="w-6 h-6 rounded border border-ink/30 bg-stone-50 hover:bg-stone-200 flex items-center justify-center font-bold text-ink"
                                    >
                                      +
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Selected Order Summary */}
                  <div className="p-3 rounded-lg border border-ink/20 bg-white space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-muted">
                          Selected Order Lines:
                        </span>
                        <span className="font-mono text-xs font-bold text-ink">
                          {builtOrderLines || <span className="text-muted italic font-normal">None selected (default order lines will be used)</span>}
                        </span>
                      </div>
                      {builtOrderLines && (
                        <button
                          type="button"
                          onClick={clearOrderLines}
                          className="text-xs text-red-600 hover:text-red-800 font-semibold"
                        >
                          Clear Selection
                        </button>
                      )}
                    </div>

                    {/* Chips for Selected SKUs */}
                    {Object.keys(orderQuantities).length > 0 && (
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {Object.entries(orderQuantities).map(([sku, qty]) => (
                          <span
                            key={sku}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-ink/30 bg-cream text-xs font-mono font-bold text-ink"
                          >
                            <span>{sku}: {qty}</span>
                            <button
                              type="button"
                              onClick={() => updateQuantity(sku, -qty)}
                              className="hover:text-red-700"
                              aria-label={`Remove ${sku}`}
                            >
                              <X size={12} />
                            </button>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                /* Read-only Display of Order Lines / SKUs for other stages */
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
              )}

              {/* Visual Reference Image Upload & Ephemeral Run Control */}
              <div className="p-4 rounded-xl border-2 border-dashed border-ink/30 bg-cream/30 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <ImageIcon size={18} className="text-ink" />
                    <div>
                      <span className="text-xs font-bold uppercase tracking-wider text-ink block">
                        Visual Reference Upload
                      </span>
                      <span className="text-[11px] text-muted">
                        Upload custom carton/unit photo (JPG, PNG, WebP)
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <label className="btn-secondary text-xs py-1.5 px-3 cursor-pointer inline-flex items-center gap-1.5">
                      <Upload size={14} />
                      <span>{uploadCompressing ? 'Compressing...' : 'Choose Image'}</span>
                      <input
                        type="file"
                        accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
                        onChange={handleImageChange}
                        disabled={uploadCompressing || loading}
                        className="hidden"
                      />
                    </label>

                    {selectedUploadFile && (
                      <button
                        type="button"
                        onClick={handleClearUpload}
                        className="btn-outline text-xs py-1.5 px-2.5 text-muted hover:text-ink"
                        title="Discard selected image"
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>

                {/* Error Banner if upload/compression fails */}
                {uploadError && (
                  <div className="p-3 rounded-lg border border-red-500/30 bg-red-50 text-xs text-red-800 flex items-start gap-2">
                    <AlertTriangle size={15} className="shrink-0 text-red-600 mt-0.5" />
                    <div>
                      <strong>Upload Rejected:</strong> {uploadError}
                    </div>
                  </div>
                )}

                {/* Selected Image Preview with Compression Stats & Run Trigger */}
                {uploadFilePreview && (
                  <div className="p-3 rounded-lg border border-ink/20 bg-white space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <img
                          src={uploadFilePreview.url}
                          alt={uploadFilePreview.name}
                          className="w-16 h-16 rounded object-cover border border-ink/20 shrink-0"
                        />
                        <div className="space-y-1">
                          <div className="font-mono text-xs font-bold text-ink truncate max-w-xs">
                            {uploadFilePreview.name}
                          </div>
                          <div className="flex items-center gap-2 text-[11px] font-mono text-muted">
                            <span>Orig: {uploadFilePreview.originalSize}</span>
                            <span>&rarr;</span>
                            <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 font-bold">
                              Compressed: {uploadFilePreview.compressedSize} (&lt; 3 MB)
                            </span>
                          </div>
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={handleRunUpload}
                        disabled={loading || uploadCompressing}
                        className="btn-primary text-xs py-2 px-4 inline-flex items-center gap-1.5 shrink-0"
                      >
                        {loading ? (
                          <>
                            <Loader2 size={14} className="animate-spin" />
                            <span>Processing...</span>
                          </>
                        ) : (
                          <>
                            <Play size={14} className="fill-ink" />
                            <span>Run {agent.name} on Uploaded Image</span>
                          </>
                        )}
                      </button>
                    </div>

                    <div className="text-[11px] text-muted italic flex items-center gap-1 border-t border-ink/10 pt-2">
                      <Info size={13} className="shrink-0 text-amber-700" />
                      <span>
                        Uploaded images are stored in ephemeral storage and will disappear on container restart. The Evidence Record captures the sha256 hash.
                      </span>
                    </div>
                  </div>
                )}

                {/* If no upload selected, show instructions */}
                {!uploadFilePreview && (
                  <div className="p-3 rounded-lg border border-ink/15 bg-stone-50/70 text-xs text-muted flex items-start gap-2">
                    <Info size={15} className="shrink-0 text-ink/60 mt-0.5" />
                    <p className="leading-relaxed">
                      You can run the agent on an uploaded image (automatically resized and compressed client-side to under 3 MB), or use the button below to run standard orchestrator unit check.
                    </p>
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

              {/* Ad-Hoc Ephemeral Upload Banner */}
              {checkResult.isAdHocUpload && (
                <div className="p-3.5 rounded-lg border border-amber-600/30 bg-amber-50/90 text-amber-950 flex items-start gap-2.5 text-xs">
                  <AlertTriangle size={16} className="text-amber-700 shrink-0 mt-0.5" />
                  <div className="space-y-0.5">
                    <div className="font-bold">Ad-Hoc Ephemeral Run</div>
                    <p className="text-amber-800 text-[11px] leading-relaxed">
                      {checkResult.storageNote || 'Uploaded images are stored in ephemeral storage and will disappear on container restart.'} The Evidence Record content-addresses the photo via SHA-256 without persisting raw bytes.
                    </p>
                  </div>
                </div>
              )}

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

                  {/* Order Lines Manifest Comparison (Pack Manager) */}
                  {stage === 'pack' && (
                    <div className="p-4 rounded-xl border-2 border-ink/20 bg-stone-50 space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink/15 pb-2">
                        <div className="flex items-center gap-2">
                          <Package size={16} className="text-ink" />
                          <h4 className="font-serif text-base font-bold text-ink">
                            Order Comparison & Verification (Pack Manager)
                          </h4>
                        </div>
                        <span className="text-[11px] font-mono text-muted">
                          Carton Verification Against Order Lines
                        </span>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Column A: Expected Order Lines */}
                        <div className="p-3.5 rounded-lg border border-ink/20 bg-white space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-bold uppercase tracking-wider text-muted">
                              Expected Order Lines (Checked Against)
                            </span>
                            <span className="text-[10px] font-mono text-muted">
                              {checkResult.evidence?.subject?.refs?.order_id || 'Order Manifest'}
                            </span>
                          </div>
                          <div className="font-mono text-xs font-bold text-ink bg-stone-100 p-2 rounded border border-ink/10 break-all">
                            {checkResult.evidence?.payload?.order_lines || builtOrderLines || 'None specified'}
                          </div>

                          {/* Itemized Expected SKUs */}
                          <div className="space-y-1.5 pt-1">
                            {(() => {
                              const linesStr = checkResult.evidence?.payload?.order_lines || builtOrderLines || ''
                              if (!linesStr) return <p className="text-xs text-muted italic">No order lines specified.</p>
                              const parts = linesStr.split(';').map((p) => p.trim()).filter(Boolean)
                              return parts.map((part) => {
                                const [sku, qty] = part.split(':')
                                const catItem = catalogue.find((c) => c.sku === sku)
                                return (
                                  <div key={sku} className="flex items-center justify-between text-xs p-2 rounded border border-ink/10 bg-stone-50 font-mono">
                                    <div className="truncate mr-2">
                                      <strong className="text-ink">{sku}</strong>
                                      {catItem && <div className="text-[10px] text-muted font-sans truncate">{catItem.title || catItem.name}</div>}
                                    </div>
                                    <div className="text-right shrink-0">
                                      <span className="px-2 py-0.5 rounded bg-ink/10 text-ink font-bold text-xs">Qty: {qty || 1}</span>
                                      {catItem?.expected_packaging && (
                                        <div className="text-[9px] text-muted uppercase tracking-wider mt-0.5">{catItem.expected_packaging}</div>
                                      )}
                                    </div>
                                  </div>
                                )
                              })
                            })()}
                          </div>
                        </div>

                        {/* Column B: Observed in Box & Operator Decision */}
                        <div className="p-3.5 rounded-lg border border-ink/20 bg-white space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-bold uppercase tracking-wider text-muted">
                              Observed in Box & Operator Action
                            </span>
                            <span className="text-xs font-mono font-bold px-2 py-0.5 rounded border border-ink/20 bg-cream">
                              Action: {checkResult.evidence?.payload?.operator_action || 'N/A'}
                            </span>
                          </div>

                          {/* Observed items */}
                          {checkResult.evidence?.payload?.observations && checkResult.evidence.payload.observations.length > 0 ? (
                            <div className="space-y-1.5">
                              {checkResult.evidence.payload.observations.map((obs, idx) => (
                                <div key={idx} className="flex items-center justify-between text-xs p-2 rounded border border-ink/10 bg-stone-50 font-mono">
                                  <div>
                                    <strong className="text-ink">{obs.sku}</strong>
                                    <div className="text-[10px] text-muted">
                                      Conf: {Math.round((obs.count_confidence || 1.0) * 100)}%
                                    </div>
                                  </div>
                                  <span className="px-2 py-0.5 rounded bg-emerald-100 border border-emerald-300 text-emerald-900 font-bold">
                                    Count: {obs.count}
                                  </span>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="p-3 rounded-lg bg-stone-50 border border-ink/10 text-xs text-muted">
                              {checkResult.evidence?.payload?.error_detail || 'No visual carton observations recorded.'}
                            </div>
                          )}

                          {/* Reason codes summary */}
                          {checkResult.evidence?.payload?.reason_codes && (
                            <div className="pt-1 text-[11px] font-mono text-muted space-y-1 border-t border-ink/10">
                              {Object.entries(checkResult.evidence.payload.reason_codes).map(([k, code]) => (
                                <div key={k} className="flex justify-between">
                                  <span>{k}:</span>
                                  <strong className={code === 'OK' ? 'text-emerald-700' : 'text-amber-700'}>{code}</strong>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

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
