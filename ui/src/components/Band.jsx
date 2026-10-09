import React from 'react'

/**
 * Full-width colored section wrapper matching the "Wellnessty" signature style.
 * Alternates between: cream, teal, peach, and charcoal.
 */
export default function Band({
  color = 'cream',
  title,
  description,
  badge,
  action,
  children,
  className = '',
  id,
}) {
  const isCharcoal = color === 'charcoal'

  const bgClasses = {
    cream: 'bg-cream text-ink',
    teal: 'bg-teal text-ink',
    peach: 'bg-peach text-ink',
    charcoal: 'bg-charcoal text-cream',
  }[color] || 'bg-cream text-ink'

  const titleColor = isCharcoal ? 'text-cream' : 'text-ink'
  const descColor = isCharcoal ? 'text-[#E0D8C3]' : 'text-muted'

  return (
    <section id={id} className={`w-full py-10 md:py-14 px-4 sm:px-6 lg:px-8 transition-colors ${bgClasses} ${className}`}>
      <div className="max-w-6xl mx-auto">
        {(title || description || action || badge) && (
          <div className="mb-6 md:mb-8 flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div>
              {badge && <div className="mb-2">{badge}</div>}
              {title && (
                <h2 className={`text-2xl md:text-3xl lg:text-4xl font-serif font-bold tracking-tight ${titleColor}`}>
                  {title}
                </h2>
              )}
              {description && (
                <p className={`mt-1.5 text-sm md:text-base ${descColor} max-w-3xl leading-relaxed`}>
                  {description}
                </p>
              )}
            </div>
            {action && <div className="shrink-0">{action}</div>}
          </div>
        )}
        {children}
      </div>
    </section>
  )
}
