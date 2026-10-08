import React, { useState } from 'react'
import { NavLink, Link } from 'react-router-dom'
import { useSession } from '../context/SessionContext'
import { BRAND_NAME } from '../config/brand.js'
import {
  Layers,
  ClipboardList,
  Menu,
  X,
  User,
} from 'lucide-react'

export default function NavBar() {
  const { org, operator, switchOrg, updateOperator, sessionWorkflows } = useSession()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const reviewCount = sessionWorkflows.filter(
    (w) => w.org_id === org && (w.status === 'BLOCKED' || w.final_outcome?.outcome === 'NEEDS_REVIEW')
  ).length

  const navLinks = [
    {
      to: '/app/dashboard',
      label: 'Dashboard',
      icon: Layers,
      tooltip: `An overview of the ${BRAND_NAME} workflow and its five agents. Select an agent to work with it.`,
    },
    {
      to: '/app/review',
      label: 'Review Queue',
      icon: ClipboardList,
      badge: reviewCount,
      tooltip: 'Units where an agent returned UNCERTAIN and a person must decide. Record who decided and why, then resume the workflow.',
    },
  ]

  const linkClass = ({ isActive }) =>
    `px-3 py-1.5 rounded-xl border-2 font-bold text-xs sm:text-sm flex items-center gap-1.5 transition-all focus:outline-none focus-visible:ring-2 ${
      isActive
        ? 'bg-mustard text-ink border-ink shadow-[2px_2px_0_var(--ink)] -translate-y-0.5'
        : 'bg-card text-ink border-ink/30 hover:border-ink hover:bg-stone-50'
    }`

  const orgTooltip =
    "Selects which organisation's data you view. It does not authenticate you. Tenant isolation is enforced by org_id in the orchestrator."

  return (
    <header className="w-full bg-cream border-b-2 border-ink py-2.5 px-4 sm:px-6 lg:px-8 sticky top-0 z-40">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-3">
        {/* LEFT: Logo + BRAND_NAME + Immediately beside it links: Dashboard & Review Queue */}
        <div className="flex items-center gap-3 sm:gap-4 shrink-0">
          <Link
            to="/"
            className="flex items-center gap-2.5 text-ink hover:opacity-90 transition-opacity focus:outline-none focus-visible:ring-2 rounded-xl"
            aria-label={`${BRAND_NAME} home`}
          >
            <div className="w-9 h-9 rounded-xl bg-mustard border-2 border-ink shadow-[2px_2px_0_var(--ink)] flex items-center justify-center font-serif font-black text-xl text-ink">
              {BRAND_NAME.charAt(0)}
            </div>
            <span className="font-serif font-bold text-2xl text-ink tracking-tight">
              {BRAND_NAME}
            </span>
          </Link>

          {/* Desktop Navigation Links (Dashboard & Review Queue ONLY) */}
          <nav className="hidden md:flex items-center gap-2 ml-1" aria-label="Main Navigation">
            {navLinks.map((item) => {
              const Icon = item.icon
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={linkClass}
                  title={item.tooltip}
                  aria-label={`${item.label}: ${item.tooltip}`}
                >
                  <Icon size={15} />
                  <span>{item.label}</span>
                  {item.badge > 0 && (
                    <span className="ml-1 px-1.5 py-0.2 rounded-full bg-[#D64545] text-white text-[11px] font-mono font-bold">
                      {item.badge}
                    </span>
                  )}
                </NavLink>
              )
            })}
          </nav>
        </div>

        {/* RIGHT: Two-option organisation switch and editable Operator field. Nothing else. */}
        <div className="flex items-center gap-2 sm:gap-3 text-xs">
          {/* Segmented Two-Option Organisation Switch */}
          <div
            className="inline-flex items-center p-0.5 bg-card border-2 border-ink rounded-xl shadow-sm"
            role="radiogroup"
            aria-label="Organisation Switch"
            title={orgTooltip}
            aria-description={orgTooltip}
          >
            <button
              type="button"
              role="radio"
              aria-checked={org === 'org_demo_alpha'}
              onClick={() => switchOrg('org_demo_alpha')}
              className={`px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all focus:outline-none focus-visible:ring-1 ${
                org === 'org_demo_alpha'
                  ? 'bg-mustard text-ink border border-ink shadow-[1px_1px_0_var(--ink)]'
                  : 'text-muted hover:text-ink'
              }`}
            >
              <span className="hidden sm:inline">org_demo_</span>alpha
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={org === 'org_demo_bravo'}
              onClick={() => switchOrg('org_demo_bravo')}
              className={`px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all focus:outline-none focus-visible:ring-1 ${
                org === 'org_demo_bravo'
                  ? 'bg-mustard text-ink border border-ink shadow-[1px_1px_0_var(--ink)]'
                  : 'text-muted hover:text-ink'
              }`}
            >
              <span className="hidden sm:inline">org_demo_</span>bravo
            </button>
          </div>

          {/* Operator Name Field */}
          <div
            className="flex items-center gap-1.5 bg-card border-2 border-ink rounded-xl px-2.5 py-1 shadow-sm"
            title="Operator actor prefilled for Review Queue overrides"
          >
            <User size={13} className="text-muted hidden xs:inline shrink-0" />
            <label
              htmlFor="topbar-operator-input"
              className="font-bold text-muted uppercase text-[10px] tracking-wider select-none shrink-0"
            >
              Operator
            </label>
            <input
              id="topbar-operator-input"
              type="text"
              value={operator}
              onChange={(e) => updateOperator(e.target.value)}
              placeholder="Operator"
              className="font-mono font-bold text-xs text-ink bg-transparent border-none outline-none w-20 sm:w-28 focus:ring-0 p-0"
            />
          </div>

          {/* Narrow Screens: Mobile menu button for Dashboard & Review Queue */}
          <div className="flex md:hidden items-center">
            <button
              type="button"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="p-1.5 border-2 border-ink rounded-xl bg-card text-ink shadow-[1px_1px_0_var(--ink)] focus:outline-none focus-visible:ring-2"
              aria-label={mobileMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
            >
              {mobileMenuOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Drawer (links only) */}
      {mobileMenuOpen && (
        <div className="md:hidden mt-2 pt-2 border-t-2 border-ink/20 flex flex-col gap-1.5">
          <nav className="flex flex-col gap-1" aria-label="Mobile Navigation">
            {navLinks.map((item) => {
              const Icon = item.icon
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={() => setMobileMenuOpen(false)}
                  className={linkClass}
                  title={item.tooltip}
                >
                  <Icon size={15} />
                  <span>{item.label}</span>
                  {item.badge > 0 && (
                    <span className="ml-auto px-1.5 py-0.2 rounded-full bg-[#D64545] text-white text-[11px] font-mono font-bold">
                      {item.badge}
                    </span>
                  )}
                </NavLink>
              )
            })}
          </nav>
        </div>
      )}
    </header>
  )
}
