import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useSession } from '../context/SessionContext'
import Band from '../components/Band'
import CheckTable from '../components/CheckTable'
import VerdictBadge from '../components/VerdictBadge'
import ErrorBanner from '../components/ErrorBanner'
import EvidenceRecordPanel from '../components/EvidenceRecordPanel'
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
  Trash2,
  Camera,
  RefreshCw,
} from 'lucide-react'

// Client-side image resize & compression to under 4 MB (Vercel serverless limit)
async function compressImageFile(file, maxBytes = 4 * 1024 * 1024) {
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
  const [unitId, setUnitId] = useState(stage === 'pack' ? 'UNIT-0010' : 'UNIT-0011')
  const [orderId, setOrderId] = useState(stage === 'pack' ? 'ORD-UNIT-0010' : '')
  const [route, setRoute] = useState('auto')
  const [returned, setReturned] = useState('auto')

  // Pack Manager Multi-Photo State & Catalogue Picker Modal
  const [packPhotos, setPackPhotos] = useState([])
  const [cataloguePickerOpen, setCataloguePickerOpen] = useState(false)

  // Discovered Order Lines / SKUs from runs
  const [discoveredRefs, setDiscoveredRefs] = useState(null)

  // Local image previews & upload state (for non-pack stages)
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

  // Set defaults when stage changes
  useEffect(() => {
    if (stage === 'pack') {
      setUnitId((prev) => (prev === 'UNIT-0011' || !prev ? 'UNIT-0010' : prev))
      setOrderId((prev) => (!prev ? 'ORD-UNIT-0010' : prev))
    }
  }, [stage])

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
    setPackPhotos([])
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

  // Handle Pack Manager multi-photo selection & client-side compression
  const handlePackPhotosChange = async (e) => {
    const files = Array.from(e.target.files || [])
    if (!files.length) return

    setUploadError(null)
    setUploadCompressing(true)

    try {
      if (packPhotos.length + files.length > 5) {
        throw new Error(`Maximum 5 photographs allowed. You already have ${packPhotos.length} photo(s).`)
      }

      const compressedList = []
      for (const file of files) {
        const compressed = await compressImageFile(file, 4 * 1024 * 1024)
        compressedList.push({
          file: compressed,
          name: compressed.name,
          previewUrl: URL.createObjectURL(compressed),
          sizeFormatted: (compressed.size / (1024 * 1024)).toFixed(2) + ' MB',
          bytes: compressed.size,
        })
      }

      const combined = [...packPhotos, ...compressedList]
      const totalBytes = combined.reduce((acc, p) => acc + p.bytes, 0)
      if (totalBytes > 4.2 * 1024 * 1024) {
        throw new Error(`Total photos size (${(totalBytes / (1024 * 1024)).toFixed(2)} MB) exceeds 4.5 MB limit even after compression. Please select fewer or smaller photos.`)
      }

      setPackPhotos(combined)
    } catch (err) {
      setUploadError(err.message || 'Image processing failed')
    } finally {
      setUploadCompressing(false)
      e.target.value = ''
    }
  }

  const handleRemovePackPhoto = (idx) => {
    setPackPhotos((prev) => {
      const removed = prev[idx]
      if (removed?.previewUrl) {
        URL.revokeObjectURL(removed.previewUrl)
      }
      return prev.filter((_, i) => i !== idx)
    })
  }

  // Execute Pack Manager Single-Flow Check via POST /stages/pack/run-upload
  const handleRunPackCheck = async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (!unitId.trim()) {
      setError({ message: 'Unit ID is required' })
      return
    }
    if (!orderId.trim()) {
      setError({ message: 'Order ID is required' })
      return
    }
    if (Object.keys(orderQuantities).length === 0 || !builtOrderLines) {
      setError({ message: 'At least one order line is required. Click "+ Add Item" to select from catalogue.' })
      return
    }
    if (packPhotos.length === 0) {
      setError({ message: 'At least one open-box photograph is required (1 to 5 photos).' })
      return
    }

    setLoading(true)
    setError(null)
    setUploadError(null)
    setCheckResult(null)

    try {
      const res = await runStageUpload({
        stage: 'pack',
        files: packPhotos.map((p) => p.file),
        unit_id: unitId.trim(),
        order_id: orderId.trim(),
        org_id: org,
        order_lines: builtOrderLines,
        route: 'mfn',
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

            {stage === 'pack' ? (
              /* Pack Manager Single-Flow Form */
              <form onSubmit={handleRunPackCheck} className="space-y-6">
                {/* Order ID & Unit ID */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="pack-order-id" className="block text-xs font-bold uppercase tracking-wider text-ink mb-1.5">
                      Order ID *
                    </label>
                    <input
                      id="pack-order-id"
                      type="text"
                      required
                      value={orderId}
                      onChange={(e) => setOrderId(e.target.value)}
                      placeholder="e.g. ORD-UNIT-0010"
                      className="w-full px-3.5 py-2.5 border-2 border-ink rounded-xl font-mono text-sm bg-white focus:outline-none"
                    />
                    <span className="text-[11px] text-muted block mt-1">
                      Customer or channel order identifier
                    </span>
                  </div>

                  <div>
                    <label htmlFor="pack-unit-id" className="block text-xs font-bold uppercase tracking-wider text-ink mb-1.5">
                      Unit ID *
                    </label>
                    <input
                      id="pack-unit-id"
                      type="text"
                      required
                      value={unitId}
                      onChange={(e) => setUnitId(e.target.value)}
                      placeholder="UNIT-XXXX"
                      className="w-full px-3.5 py-2.5 border-2 border-ink rounded-xl font-mono text-sm bg-white focus:outline-none"
                    />
                    <span className="text-[11px] text-muted block mt-1">
                      Physical inventory unit identifier
                    </span>
                  </div>
                </div>

                {/* Order Lines Builder */}
                <div className="p-5 rounded-xl border-2 border-ink/30 bg-stone-50 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 mb-0.5">
                        <Package size={16} className="text-ink" />
                        <span className="font-mono text-xs font-bold uppercase tracking-wider text-muted">
                          Order Lines
                        </span>
                      </div>
                      <p className="text-xs text-muted">
                        Select products from your catalogue and set quantities. (Quantities are never sent to the vision model).
                      </p>
                    </div>

                    <button
                      type="button"
                      onClick={() => setCataloguePickerOpen(true)}
                      className="btn-primary text-xs py-2 px-3.5 flex items-center gap-1.5 shrink-0"
                    >
                      <Plus size={14} />
                      <span>+ Add Item</span>
                    </button>
                  </div>

                  {Object.keys(orderQuantities).length === 0 ? (
                    <div className="py-6 px-4 text-center text-xs text-muted border-2 border-dashed border-stone-300 rounded-xl bg-white space-y-2">
                      <Package size={24} className="mx-auto text-muted/50" />
                      <p>No order lines added yet. Click &ldquo;+ Add Item&rdquo; above to select products from your catalogue.</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="border border-ink/20 rounded-xl bg-white overflow-hidden divide-y divide-stone-200">
                        {Object.entries(orderQuantities).map(([sku, qty]) => {
                          const item = catalogue.find((c) => c.sku === sku)
                          return (
                            <div key={sku} className="p-3 flex items-center justify-between gap-3 text-xs">
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                  <span className="font-mono font-bold text-ink">{sku}</span>
                                  {item?.packaging_type && (
                                    <span className="px-1.5 py-0.5 rounded bg-stone-100 text-[10px] uppercase font-mono text-muted">
                                      {item.packaging_type}
                                    </span>
                                  )}
                                </div>
                                {item && (
                                  <div className="text-[11px] text-muted truncate">{item.title || item.name}</div>
                                )}
                              </div>

                              <div className="flex items-center gap-3 shrink-0">
                                <div className="inline-flex items-center border border-ink/30 rounded-lg bg-stone-50 overflow-hidden">
                                  <button
                                    type="button"
                                    onClick={() => updateQuantity(sku, -1)}
                                    className="w-8 h-8 flex items-center justify-center hover:bg-stone-200 text-ink font-bold text-sm transition-colors"
                                    title="Decrease quantity"
                                  >
                                    -
                                  </button>
                                  <span className="w-8 text-center font-mono font-bold text-xs text-ink">{qty}</span>
                                  <button
                                    type="button"
                                    onClick={() => updateQuantity(sku, 1)}
                                    className="w-8 h-8 flex items-center justify-center hover:bg-stone-200 text-ink font-bold text-sm transition-colors"
                                    title="Increase quantity"
                                  >
                                    +
                                  </button>
                                </div>

                                <button
                                  type="button"
                                  onClick={() => updateQuantity(sku, -qty)}
                                  className="p-1.5 text-stone-400 hover:text-rose-600 transition-colors rounded"
                                  title={`Remove ${sku}`}
                                >
                                  <Trash2 size={16} />
                                </button>
                              </div>
                            </div>
                          )
                        })}
                      </div>

                      <div className="flex justify-between items-center text-[11px] pt-1">
                        <span className="font-mono text-muted">
                          Selected Order Lines: <strong className="text-ink">{builtOrderLines}</strong>
                        </span>
                        <button
                          type="button"
                          onClick={clearOrderLines}
                          className="text-stone-500 hover:text-rose-600 font-medium"
                        >
                          Clear All Items
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* Open-Box Photographs */}
                <div className="p-5 rounded-xl border-2 border-dashed border-ink/30 bg-cream/30 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <Camera size={18} className="text-ink" />
                        <span className="text-xs font-bold uppercase tracking-wider text-ink block">
                          Open-Box Photographs
                        </span>
                      </div>
                      <span className="text-[11px] font-mono font-semibold text-muted block mt-0.5">
                        1 to 5 photos, max 4MB each, total &lt;= 4.5MB Vercel limit
                      </span>
                      <p className="text-xs text-muted mt-1">
                        Multiple views are inspected as different angles of the same box. Each physical item is counted once.
                      </p>
                    </div>

                    <div>
                      <label className="btn-secondary text-xs py-2 px-3.5 cursor-pointer inline-flex items-center gap-1.5">
                        <Upload size={14} />
                        <span>{uploadCompressing ? 'Compressing...' : '+ Add Photo(s)'}</span>
                        <input
                          type="file"
                          accept="image/*,.jpg,.jpeg,.png,.webp"
                          multiple
                          onChange={handlePackPhotosChange}
                          disabled={uploadCompressing || loading || packPhotos.length >= 5}
                          className="hidden"
                        />
                      </label>
                    </div>
                  </div>

                  {uploadError && (
                    <div className="p-3 rounded-lg border border-rose-300 bg-rose-50 text-xs text-rose-800 flex items-start gap-2">
                      <AlertTriangle size={15} className="shrink-0 text-rose-600 mt-0.5" />
                      <div>
                        <strong>Photo Upload Error:</strong> {uploadError}
                      </div>
                    </div>
                  )}

                  {/* Thumbnails grid */}
                  {packPhotos.length > 0 ? (
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 pt-2">
                      {packPhotos.map((photo, idx) => (
                        <div key={idx} className="relative group rounded-xl border-2 border-ink overflow-hidden bg-white shadow-sm">
                          <img
                            src={photo.previewUrl}
                            alt={photo.name}
                            className="w-full h-24 object-cover"
                          />
                          <button
                            type="button"
                            onClick={() => handleRemovePackPhoto(idx)}
                            className="absolute top-1 right-1 p-1 rounded-full bg-black/70 hover:bg-rose-600 text-white transition-colors"
                            title="Remove photo"
                          >
                            <X size={12} />
                          </button>
                          <div className="p-1.5 bg-white/95 text-[10px] font-mono truncate border-t border-ink/10">
                            <div className="truncate font-semibold text-ink">{photo.name}</div>
                            <div className="text-muted">{photo.sizeFormatted}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="py-6 px-4 text-center text-xs text-muted border border-dashed border-stone-300 rounded-xl bg-white/70">
                      No photos attached. Attach 1 to 5 open-box photos to run pack check. Phone camera capture supported.
                    </div>
                  )}
                </div>

                {/* Loading notice */}
                {loading && (
                  <div className="p-3.5 rounded-xl border border-mustard/60 bg-amber-50/90 text-xs text-amber-950 flex items-start gap-2.5">
                    <Loader2 size={16} className="animate-spin text-amber-700 shrink-0 mt-0.5" />
                    <div className="space-y-0.5">
                      <span className="font-bold text-amber-900 block">Inspecting open-box photographs with vision model...</span>
                      <span className="text-amber-800 text-[11px] block">This check can take up to a minute when multiple photos or retries are processed.</span>
                    </div>
                  </div>
                )}

                {/* Single "Run Pack Check" Button */}
                <div className="pt-2 flex flex-col sm:flex-row items-center justify-between gap-4">
                  <div className="text-xs text-muted self-start sm:self-center">
                    Tenant: <strong className="font-mono text-ink">{org}</strong> &bull; Route: <strong className="font-mono text-ink">mfn</strong>
                  </div>

                  <button
                    type="submit"
                    disabled={loading || uploadCompressing || !unitId.trim() || !orderId.trim() || packPhotos.length === 0 || !builtOrderLines}
                    className="btn-primary text-base py-3 px-8 flex items-center gap-2 w-full sm:w-auto justify-center disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {loading ? (
                      <>
                        <Loader2 size={18} className="animate-spin" />
                        <span>Running Pack Check...</span>
                      </>
                    ) : (
                      <>
                        <Play size={18} className="fill-ink" />
                        <span>Run Pack Check</span>
                      </>
                    )}
                  </button>
                </div>
              </form>
            ) : (
              /* Non-Pack Agent Stages: Standard Multi-Route Form */
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

                {/* Read-only Display of Order Lines / SKUs for other stages */}
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
                                Compressed: {uploadFilePreview.compressedSize} (&lt; 4 MB)
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
                        You can run the agent on an uploaded image (automatically resized and compressed client-side to under 4 MB), or use the button below to run standard orchestrator unit check.
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
            )}
          </div>

          {/* Catalogue Picker Modal (Pack Manager) */}
          {cataloguePickerOpen && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/60 backdrop-blur-xs">
              <div className="bg-card border-2 border-ink rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden animate-in fade-in duration-200">
                {/* Modal Header */}
                <div className="p-4 sm:p-5 border-b border-rule flex items-center justify-between gap-3">
                  <div>
                    <h3 className="font-serif text-lg font-bold text-ink flex items-center gap-2">
                      <Package size={18} />
                      <span>Select Products from Catalogue</span>
                    </h3>
                    <p className="text-xs text-muted">
                      Tenant: <strong className="font-mono text-ink">{org}</strong> &bull; {catalogue.length} items in catalogue
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setCataloguePickerOpen(false)}
                    className="p-1.5 rounded-lg text-muted hover:text-ink hover:bg-stone-100 transition-colors"
                  >
                    <X size={18} />
                  </button>
                </div>

                {/* Search Input */}
                <div className="p-4 border-b border-rule bg-stone-50">
                  <div className="relative">
                    <Search size={16} className="absolute left-3.5 top-3 text-muted pointer-events-none" />
                    <input
                      type="text"
                      autoFocus
                      value={catalogueSearch}
                      onChange={(e) => setCatalogueSearch(e.target.value)}
                      placeholder="Search SKU, product title, barcode..."
                      className="w-full pl-10 pr-8 py-2 border-2 border-ink rounded-xl text-xs font-mono bg-white focus:outline-none"
                    />
                    {catalogueSearch && (
                      <button
                        type="button"
                        onClick={() => setCatalogueSearch('')}
                        className="absolute right-3 top-2.5 text-muted hover:text-ink text-xs"
                      >
                        <X size={14} />
                      </button>
                    )}
                  </div>
                </div>

                {/* Products List */}
                <div className="p-4 overflow-y-auto space-y-2 flex-1">
                  {filteredCatalogue.length === 0 ? (
                    <div className="py-8 text-center text-xs text-muted">
                      No products match &ldquo;{catalogueSearch}&rdquo;.
                    </div>
                  ) : (
                    filteredCatalogue.map((item) => {
                      const currentQty = orderQuantities[item.sku] || 0
                      return (
                        <div
                          key={item.sku}
                          className="p-3 rounded-xl border border-ink/20 hover:border-ink bg-white flex items-center justify-between gap-3 transition-colors text-xs"
                        >
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-mono font-bold text-ink">{item.sku}</span>
                              {item.expected_packaging && (
                                <span className="px-1.5 py-0.5 rounded bg-stone-100 text-[10px] font-mono text-muted uppercase">
                                  {item.expected_packaging}
                                </span>
                              )}
                              {item.hazmat && (
                                <span className="px-1.5 py-0.5 rounded bg-amber-100 text-[10px] font-bold text-amber-900 border border-amber-300">
                                  HAZMAT
                                </span>
                              )}
                            </div>
                            <div className="font-sans font-semibold text-ink text-xs truncate mt-0.5">
                              {item.title || item.name}
                            </div>
                            {item.description && (
                              <div className="text-[11px] text-muted truncate mt-0.5">
                                {item.description}
                              </div>
                            )}
                          </div>

                          <div className="shrink-0 flex items-center gap-2">
                            {currentQty > 0 ? (
                              <div className="inline-flex items-center border border-ink/30 rounded-lg bg-stone-50 overflow-hidden">
                                <button
                                  type="button"
                                  onClick={() => updateQuantity(item.sku, -1)}
                                  className="w-7 h-7 flex items-center justify-center hover:bg-stone-200 text-ink font-bold"
                                >
                                  -
                                </button>
                                <span className="w-7 text-center font-mono font-bold text-xs">{currentQty}</span>
                                <button
                                  type="button"
                                  onClick={() => updateQuantity(item.sku, 1)}
                                  className="w-7 h-7 flex items-center justify-center hover:bg-stone-200 text-ink font-bold"
                                >
                                  +
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => updateQuantity(item.sku, 1)}
                                className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1"
                              >
                                <Plus size={13} />
                                <span>Add</span>
                              </button>
                            )}
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>

                {/* Modal Footer */}
                <div className="p-4 border-t border-rule bg-stone-50 flex items-center justify-between">
                  <span className="text-xs font-mono text-muted">
                    {Object.keys(orderQuantities).length} item(s) selected
                  </span>
                  <button
                    type="button"
                    onClick={() => setCataloguePickerOpen(false)}
                    className="btn-primary text-xs py-2 px-5"
                  >
                    Done
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Error Banner / Wrong-Tenant Refusal */}
          {error && (
            <div className="space-y-3">
              <ErrorBanner
                error={error}
                onDismiss={() => setError(null)}
                title={error.status === 404 ? 'Cross-Tenant Request Refused' : 'Stage Error'}
              />
              <div className="flex items-center justify-end">
                <button
                  type="button"
                  onClick={stage === 'pack' ? handleRunPackCheck : handleRunCheck}
                  className="btn-primary text-xs py-2 px-4 inline-flex items-center gap-2"
                >
                  <RefreshCw size={14} />
                  <span>Retry Check</span>
                </button>
              </div>
            </div>
          )}

          {/* Stage Result: SHOWS ONLY THIS AGENT'S RESULT */}
          {checkResult && (
            <div className="space-y-6">
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

              {/* If Stage was Skipped */}
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

              {/* If Stage Errored, show recorded error code & Retry button */}
              {(checkResult.stageResult?.state === 'error' || checkResult.stageResult?.error) && (
                <div className="p-4 rounded-xl border-2 border-[#D64545] bg-[#D64545]/10 text-sm space-y-3">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2 font-bold text-[#A02222]">
                      <ShieldAlert size={18} />
                      <span>
                        {checkResult.stageResult.error?.message?.includes('in org_') ||
                        checkResult.stageResult.error?.message?.includes('belongs to') ||
                        checkResult.stageResult.error?.code === 'tenant_mismatch'
                          ? 'Cross-Tenant Request Refused'
                          : 'Recorded Stage Error'}
                      </span>
                    </div>

                    <button
                      type="button"
                      onClick={stage === 'pack' ? handleRunPackCheck : (checkResult.isAdHocUpload ? handleRunUpload : handleRunCheck)}
                      className="btn-primary text-xs py-1.5 px-3 inline-flex items-center gap-1.5"
                    >
                      <RefreshCw size={13} />
                      <span>Retry</span>
                    </button>
                  </div>

                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-bold uppercase tracking-wider text-muted">Error Code:</span>
                      <span className="font-mono font-bold px-2 py-0.5 rounded bg-white border border-[#D64545]/40 text-[#A02222]">
                        {checkResult.stageResult.error?.code || 'stage_error'}
                      </span>
                    </div>

                    {checkResult.stageResult.error?.message && (
                      <div className="font-mono text-xs p-3 rounded-lg bg-white border border-[#D64545]/40 text-[#A02222] break-anywhere">
                        {checkResult.stageResult.error.message}
                      </div>
                    )}
                  </div>

                  {(checkResult.stageResult.error?.message?.includes('in org_') ||
                    checkResult.stageResult.error?.message?.includes('belongs to') ||
                    checkResult.stageResult.error?.code === 'tenant_mismatch') && (
                    <p className="text-xs text-stone-700">
                      This unit request was rejected by the stage agent. Tenant isolation prevents accessing records belonging to another organisation.
                    </p>
                  )}
                </div>
              )}

              {/* Evidence Record Panel */}
              {checkResult.evidence && (
                <EvidenceRecordPanel evidence={checkResult.evidence} />
              )}

              {/* Link to Review Queue if UNCERTAIN or BLOCKED */}
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
                      <span className="text-xs text-stone-800 break-anywhere">
                        {checkResult.stageResult?.error?.message ||
                          checkResult.stageResult?.uncertain_reason ||
                          'This stage returned an UNCERTAIN verdict requiring manual inspection and decision.'}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={stage === 'pack' ? handleRunPackCheck : (checkResult.isAdHocUpload ? handleRunUpload : handleRunCheck)}
                      className="btn-secondary text-xs py-2 px-3 inline-flex items-center gap-1.5 shrink-0"
                    >
                      <RefreshCw size={13} />
                      <span>Retry</span>
                    </button>
                    <Link
                      to="/app/review"
                      className="btn-primary text-xs py-2 px-3.5 shrink-0 flex items-center gap-1.5"
                    >
                      <span>Open Review Queue</span>
                      <ArrowRight size={14} />
                    </Link>
                  </div>
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
          <div>
            <h4 className="font-serif text-xl font-bold text-cream mb-4 flex items-center gap-2">
              <FileText size={18} className="text-mustard" />
              <span>Most Recent Session Record ({stage})</span>
            </h4>

            {sessionEvidence ? (
              <EvidenceRecordPanel evidence={sessionEvidence} />
            ) : (
              <div className="card-signature p-6 bg-card text-ink">
                <p className="text-xs text-muted italic">
                  No evidence recorded for this stage in the current session yet. Run a check above to produce a record.
                </p>
              </div>
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
                    <EvidenceRecordPanel key={rec.record_id} evidence={rec} />
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
