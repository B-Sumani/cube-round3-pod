import React from 'react'
import { AlertOctagon, ShieldAlert, X } from 'lucide-react'

/**
 * Prominent red outline card for workflow failures and error records.
 * Never styled as success.
 */
export default function ErrorBanner({ error, errors = [], title, onDismiss, className = '' }) {
  const allErrors = []
  if (error) {
    if (typeof error === 'string') {
      allErrors.push({ message: error })
    } else {
      allErrors.push(error)
    }
  }
  if (Array.isArray(errors)) {
    allErrors.push(...errors)
  }

  if (allErrors.length === 0) return null

  const isTenancyRefusal = allErrors.some(e => {
    const text = `${e.code || ''} ${e.message || ''} ${e.detail || ''}`.toLowerCase()
    return text.includes('tenant') || text.includes('tenancy') || text.includes('agent_rejected')
  })

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={`card-error p-5 text-ink my-4 relative ${className}`}
    >
      <div className="flex items-start gap-3.5">
        <div className="shrink-0 p-2 rounded-lg bg-[#D64545]/15 text-[#D64545] border border-[#D64545]">
          {isTenancyRefusal ? (
            <ShieldAlert size={24} aria-hidden="true" />
          ) : (
            <AlertOctagon size={24} aria-hidden="true" />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-serif text-lg font-bold text-[#A02222]">
              {title || (isTenancyRefusal ? 'Cross-Tenant Request Refused' : 'Workflow Failure Recorded')}
            </h3>
            {onDismiss && (
              <button
                type="button"
                onClick={onDismiss}
                className="p-1 rounded-md text-muted hover:text-ink hover:bg-red-100 transition-colors"
                aria-label="Dismiss error notice"
              >
                <X size={18} />
              </button>
            )}
          </div>

          <div className="mt-2 space-y-2">
            {allErrors.map((err, idx) => {
              const code = err.code || (isTenancyRefusal ? 'tenant_refusal' : 'error')
              const msg = err.message || err.detail || (typeof err === 'string' ? err : 'An unknown error occurred')
              const stage = err.stage
              const agentId = err.agent_id
              const retryable = err.retryable

              return (
                <div key={idx} className="bg-white/80 border border-[#D64545]/40 rounded-lg p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2 mb-1">
                    <span className="font-mono text-xs px-2 py-0.5 rounded bg-[#D64545] text-white font-bold tracking-wide">
                      {code}
                    </span>
                    {stage && (
                      <span className="text-xs px-2 py-0.5 rounded bg-stone-200 text-ink font-semibold">
                        Stage: {stage}
                      </span>
                    )}
                    {agentId && (
                      <span className="text-xs text-muted font-mono">
                        Agent: {agentId}
                      </span>
                    )}
                    {retryable !== undefined && (
                      <span className={`text-xs font-semibold ${retryable ? 'text-amber-700' : 'text-stone-600'}`}>
                        {retryable ? '• Retryable' : '• Non-retryable'}
                      </span>
                    )}
                  </div>
                  <p className="font-mono text-xs text-[#6B1515] break-words leading-relaxed whitespace-pre-wrap">
                    {msg}
                  </p>
                </div>
              )
            })}
          </div>

          {isTenancyRefusal && (
            <p className="mt-2 text-xs text-muted font-medium">
              Tenancy enforcement: The agent or orchestrator refused the subject for this organization. Refusals are recorded security events, never masked or returned as valid data.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
