import React from 'react'
import { CheckCircle2, XCircle, AlertTriangle, HelpCircle, MinusCircle, Clock } from 'lucide-react'

/**
 * Functional verdict badge pairing color with icon and text label.
 * Colors: PASS #2E9E6B, FAIL #D64545, UNCERTAIN #E39A0B
 */
export default function VerdictBadge({ verdict, size = 'md', className = '' }) {
  const norm = verdict ? String(verdict).toUpperCase() : null

  let config = {
    bg: 'bg-stone-100',
    text: 'text-ink',
    border: 'border-ink',
    icon: HelpCircle,
    label: verdict ? String(verdict) : 'PENDING',
  }

  if (norm === 'PASS') {
    config = {
      bg: 'bg-[#2E9E6B]/15',
      text: 'text-[#1B6F49]',
      border: 'border-[#2E9E6B]',
      icon: CheckCircle2,
      label: 'PASS',
    }
  } else if (norm === 'FAIL') {
    config = {
      bg: 'bg-[#D64545]/15',
      text: 'text-[#A02222]',
      border: 'border-[#D64545]',
      icon: XCircle,
      label: 'FAIL',
    }
  } else if (norm === 'UNCERTAIN') {
    config = {
      bg: 'bg-[#E39A0B]/20',
      text: 'text-[#9A6202]',
      border: 'border-[#E39A0B]',
      icon: AlertTriangle,
      label: 'UNCERTAIN',
    }
  } else if (norm === 'SKIPPED') {
    config = {
      bg: 'bg-stone-200/50',
      text: 'text-muted',
      border: 'border-muted',
      icon: MinusCircle,
      label: 'SKIPPED',
    }
  } else if (norm === 'PENDING') {
    config = {
      bg: 'bg-amber-50',
      text: 'text-amber-800',
      border: 'border-amber-400',
      icon: Clock,
      label: 'PENDING',
    }
  }

  const sizeClasses = {
    sm: 'text-xs px-2 py-0.5 gap-1',
    md: 'text-sm px-2.5 py-1 gap-1.5',
    lg: 'text-base px-3.5 py-1.5 gap-2 font-bold',
  }[size] || 'text-sm px-2.5 py-1 gap-1.5'

  const iconSizes = {
    sm: 14,
    md: 16,
    lg: 18,
  }[size] || 16

  const Icon = config.icon

  return (
    <span
      className={`inline-flex items-center font-bold tracking-wide rounded-md border ${config.bg} ${config.text} ${config.border} ${sizeClasses} ${className}`}
      aria-label={`Verdict: ${config.label}`}
    >
      <Icon size={iconSizes} aria-hidden="true" />
      <span>{config.label}</span>
    </span>
  )
}
