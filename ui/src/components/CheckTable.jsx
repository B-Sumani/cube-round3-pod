import React from 'react'
import VerdictBadge from './VerdictBadge'
import { AlertCircle, FileText } from 'lucide-react'

/**
 * Checks table rendering:
 * - check_key
 * - verdict (with VerdictBadge)
 * - confidence
 * - detail (expected vs observed)
 * - uncertain_reason
 */
export default function CheckTable({ checks = [], className = '' }) {
  if (!checks || checks.length === 0) {
    return (
      <div className="py-4 text-center text-sm text-muted bg-stone-50 rounded-lg border border-dashed border-stone-300">
        No checks recorded for this stage
      </div>
    )
  }

  return (
    <div className={`overflow-x-auto border-2 border-ink rounded-xl bg-card shadow-sm ${className}`}>
      <table className="w-full text-left border-collapse text-sm">
        <thead>
          <tr className="border-b-2 border-ink bg-stone-100 font-bold text-xs uppercase tracking-wider text-ink">
            <th className="py-2.5 px-3">Check Key</th>
            <th className="py-2.5 px-3">Verdict</th>
            <th className="py-2.5 px-3">Confidence</th>
            <th className="py-2.5 px-3">Detail (Expected vs Observed)</th>
            <th className="py-2.5 px-3">Uncertain Reason</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-200">
          {checks.map((chk, idx) => {
            const hasExpected = chk.expected !== undefined && chk.expected !== null
            const hasObserved = chk.observed !== undefined && chk.observed !== null

            return (
              <tr key={idx} className="hover:bg-amber-50/40 transition-colors">
                {/* check_key */}
                <td className="py-2.5 px-3 font-mono font-medium text-ink">
                  {chk.check_key}
                </td>

                {/* verdict */}
                <td className="py-2.5 px-3 whitespace-nowrap">
                  <VerdictBadge verdict={chk.verdict} size="sm" />
                </td>

                {/* confidence */}
                <td className="py-2.5 px-3 text-muted text-xs whitespace-nowrap">
                  {chk.confidence !== null && chk.confidence !== undefined
                    ? `${(chk.confidence * 100).toFixed(0)}%`
                    : '—'}
                </td>

                {/* detail: expected vs observed */}
                <td className="py-2.5 px-3 text-xs">
                  {hasExpected || hasObserved ? (
                    <div className="space-y-0.5 font-mono">
                      {hasExpected && (
                        <div className="text-stone-600">
                          <span className="font-semibold text-ink">Exp:</span>{' '}
                          {typeof chk.expected === 'object' ? JSON.stringify(chk.expected) : String(chk.expected)}
                        </div>
                      )}
                      {hasObserved && (
                        <div className="text-stone-800">
                          <span className="font-semibold text-ink">Obs:</span>{' '}
                          {typeof chk.observed === 'object' ? JSON.stringify(chk.observed) : String(chk.observed)}
                        </div>
                      )}
                    </div>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                  {chk.evidence_refs && chk.evidence_refs.length > 0 && (
                    <div className="mt-1 flex items-center gap-1 text-[11px] text-muted">
                      <FileText size={12} className="shrink-0" />
                      <span>{chk.evidence_refs.length} ref(s)</span>
                    </div>
                  )}
                </td>

                {/* uncertain_reason */}
                <td className="py-2.5 px-3 text-xs">
                  {chk.uncertain_reason ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-100 text-amber-900 border border-amber-300 font-medium">
                      <AlertCircle size={12} />
                      <span>{chk.uncertain_reason}</span>
                    </span>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
