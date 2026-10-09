import React from 'react'
import VerdictBadge from './VerdictBadge'
import { ArrowRight, Check, X, AlertTriangle, Minus, Clock } from 'lucide-react'

/**
 * Stage timeline showing all stages in order, with status and skipped routing reasons.
 */
export default function StageTimeline({
  stageResults = [],
  selectedStage,
  onSelectStage,
  className = '',
}) {
  if (!stageResults || stageResults.length === 0) return null

  return (
    <div className={`w-full overflow-x-auto pb-2 ${className}`}>
      <div className="flex items-stretch min-w-[700px] gap-2 lg:gap-3">
        {stageResults.map((sr, idx) => {
          const isSkipped = sr.state === 'skipped'
          const isError = sr.state === 'error'
          const isCompleted = sr.state === 'completed'
          const isPending = sr.state === 'pending'
          const isSelected = selectedStage === sr.stage

          let iconBg = 'bg-stone-200 text-stone-700'
          let Icon = Minus
          if (isSkipped) {
            iconBg = 'bg-stone-200 text-muted'
            Icon = Minus
          } else if (isError) {
            iconBg = 'bg-[#D64545] text-white'
            Icon = X
          } else if (isCompleted) {
            if (sr.verdict === 'PASS') {
              iconBg = 'bg-[#2E9E6B] text-white'
              Icon = Check
            } else if (sr.verdict === 'FAIL') {
              iconBg = 'bg-[#D64545] text-white'
              Icon = X
            } else {
              iconBg = 'bg-[#E39A0B] text-white'
              Icon = AlertTriangle
            }
          } else if (isPending) {
            iconBg = 'bg-mustard text-ink'
            Icon = Clock
          }

          return (
            <div key={sr.stage || idx} className="flex-1 flex items-center">
              <button
                type="button"
                onClick={() => onSelectStage && onSelectStage(sr.stage)}
                className={`w-full text-left p-3.5 rounded-xl border-2 transition-all flex flex-col justify-between h-full ${
                  isSelected
                    ? 'border-ink bg-card shadow-[4px_4px_0_var(--ink)] -translate-y-0.5'
                    : isSkipped
                    ? 'border-dashed border-stone-400 bg-stone-100/70 opacity-75 hover:opacity-100'
                    : 'border-ink bg-card hover:shadow-[3px_3px_0_var(--ink)] hover:-translate-y-0.5'
                }`}
                aria-label={`Stage ${sr.stage}: ${sr.state}`}
              >
                <div>
                  <div className="flex items-center justify-between gap-1 mb-2">
                    <span className="font-mono text-xs font-bold text-muted uppercase">
                      0{idx + 1}
                    </span>
                    <span className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${iconBg}`}>
                      <Icon size={12} strokeWidth={3} />
                    </span>
                  </div>

                  <div className="font-serif font-bold text-base capitalize text-ink">
                    {sr.stage}
                  </div>

                  {sr.agent_id && (
                    <div className="font-mono text-[11px] text-muted truncate mt-0.5">
                      {sr.agent_id}
                    </div>
                  )}
                </div>

                <div className="mt-3 pt-2 border-t border-stone-200 flex flex-col gap-1">
                  {isSkipped ? (
                    <div className="text-[11px] text-stone-600 font-medium">
                      <span className="font-bold text-stone-800">Skipped:</span>{' '}
                      <span className="italic truncate block" title={sr.skipped_reason}>
                        {sr.skipped_reason || 'Condition not met'}
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between">
                      <VerdictBadge verdict={sr.verdict} size="sm" />
                      {sr.duration_ms !== null && sr.duration_ms !== undefined && (
                        <span className="text-[11px] font-mono text-muted">
                          {sr.duration_ms}ms
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </button>

              {idx < stageResults.length - 1 && (
                <div className="px-1 text-ink opacity-40 shrink-0 hidden sm:block">
                  <ArrowRight size={14} />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
