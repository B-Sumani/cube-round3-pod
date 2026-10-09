import React from 'react'
import { Link } from 'react-router-dom'
import PublicLayout from '../components/PublicLayout'
import Band from '../components/Band'
import { AGENTS } from '../data/agents'
import { BRAND_NAME } from '../config/brand.js'
import {
  ArrowRight,
  Layers,
  CheckCircle2,
  AlertTriangle,
  XCircle,
} from 'lucide-react'

export default function HomePage() {
  const workflowStages = [
    {
      number: '1',
      name: 'Receiving',
      tag: 'always',
      tagType: 'always',
      shortLine: 'Checks received goods against purchase orders.',
      note: 'First stage for every unit',
    },
    {
      number: '2',
      name: 'Prep',
      tag: 'FBA only',
      tagType: 'route',
      shortLine: 'Verifies FBA packaging and label requirements.',
      note: 'Route-dependent stage',
    },
    {
      number: '2',
      name: 'Pack',
      tag: 'MFN only',
      tagType: 'route',
      shortLine: 'Matches open box contents before sealing.',
      note: 'Route-dependent stage',
    },
    {
      number: '3',
      name: 'Returns',
      tag: 'if returned',
      tagType: 'conditional',
      shortLine: 'Inspects returned items and recommends disposition.',
      note: 'Customer return evaluation',
    },
    {
      number: '4',
      name: 'Recovery',
      tag: 'always',
      tagType: 'always',
      shortLine: 'Audits channel fee charges against evidence.',
      note: 'Final audit stage',
    },
  ]

  return (
    <PublicLayout>
      {/* Hero Section: Cream Band */}
      <Band color="cream" className="py-16 md:py-24">
        <div className="max-w-4xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border-2 border-ink bg-mustard text-ink font-bold text-xs uppercase tracking-wider mb-6 shadow-sm">
            <span>Multi-Agent Operations Architecture</span>
          </div>

          {/* Platform Name only, no tagline */}
          <h1 className="font-serif text-5xl md:text-7xl font-bold text-ink tracking-tight mb-6">
            {BRAND_NAME}
          </h1>

          {/* One-paragraph description */}
          <p className="text-lg md:text-xl text-ink/85 leading-relaxed mb-8 max-w-3xl">
            One connected commerce workflow with a traceable evidence trail; agents return judgments and evidence, the orchestrator owns workflow state and the final outcome.
          </p>

          <div className="flex flex-wrap items-center gap-4">
            <Link to="/app/dashboard" className="btn-primary text-base py-3 px-6 flex items-center gap-2">
              <Layers size={18} />
              <span>Open Dashboard</span>
            </Link>
            <a href="#agents" className="btn-secondary text-base py-3 px-6 flex items-center gap-2">
              <span>See the agents</span>
              <ArrowRight size={18} />
            </a>
          </div>
        </div>
      </Band>

      {/* "Meet the agents" section: Teal Band */}
      <div id="agents">
        <Band
          color="teal"
          title="Meet the Agents"
          description="Five specialized agents inspect goods, check compliance, evaluate returns, and audit fee recovery."
        >
          {/* 5 cards in ONE single row on desktop (equal width), linking straight to /app/agents/:stage */}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-4">
            {AGENTS.map((agent) => (
              <Link
                key={agent.stage}
                to={`/app/agents/${agent.stage}`}
                className="card-signature p-4 md:p-5 bg-card flex flex-col justify-between transition-all hover:-translate-y-1 hover:shadow-[5px_5px_0_var(--ink)] cursor-pointer group text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-ink"
                aria-label={`${agent.name}: ${agent.shortPurpose}`}
              >
                <div>
                  {/* Stage number */}
                  <span className="font-mono text-xs font-bold uppercase tracking-wider text-muted block mb-1">
                    Stage {agent.stageNumber}
                  </span>

                  {/* Agent Name */}
                  <h3 className="font-serif text-lg font-bold text-ink mb-1 group-hover:text-ink/90">
                    {agent.name}
                  </h3>

                  {/* Short purpose (max ~8 words) */}
                  <p className="text-xs text-ink/80 leading-relaxed">
                    {agent.shortPurpose}
                  </p>
                </div>

                {/* Subtitle link cue */}
                <div className="mt-4 pt-2 border-t border-ink/10 flex items-center justify-between text-xs font-bold text-ink group-hover:text-mustard transition-colors">
                  <span>Work with Agent</span>
                  <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
                </div>
              </Link>
            ))}
          </div>
        </Band>
      </div>

      {/* "How it works" section: Peach Band */}
      <div id="how-it-works">
        <Band
          color="peach"
          title="How it Works"
          description="A sequential, policy-directed pipeline advancing evidence across distinct physical and financial checkpoints."
        >
          <div className="space-y-8">
            {/* End-to-End Workflow Flow: 5 separate stage cards + Final Commerce Outcome */}
            <div className="card-signature p-6 md:p-8 bg-card">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-6">
                <div>
                  <h3 className="font-serif text-2xl font-bold text-ink">
                    The End-to-End Workflow
                  </h3>
                  <p className="text-xs text-muted mt-1">
                    Every unit executes sequentially through the five specialized stages, concluding in the final outcome.
                  </p>
                </div>
                <span className="px-2.5 py-1 rounded-full border border-ink/30 bg-cream text-[11px] font-mono font-bold text-ink">
                  Deterministic Pipeline
                </span>
              </div>

              {/* 5 Separate Stage Cards + Final Commerce Outcome End Block */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
                {workflowStages.map((st, idx) => (
                  <div
                    key={st.name}
                    className="p-4 rounded-xl border-2 border-ink bg-white flex flex-col justify-between shadow-sm relative group hover:-translate-y-0.5 transition-transform"
                  >
                    <div>
                      {/* Top: Stage Number & Run Tag */}
                      <div className="flex items-center justify-between gap-1 mb-2">
                        <span className="font-mono text-xs font-bold text-muted uppercase">
                          Stage {st.number}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold uppercase tracking-wider border ${
                            st.tagType === 'route'
                              ? 'bg-mustard/40 text-ink border-ink/30'
                              : st.tagType === 'conditional'
                              ? 'bg-peach/60 text-ink border-ink/30'
                              : 'bg-cream text-muted border-ink/20'
                          }`}
                        >
                          {st.tag}
                        </span>
                      </div>

                      {/* Stage Name */}
                      <strong className="font-serif text-lg text-ink block mb-1">
                        {st.name}
                      </strong>

                      {/* One Short Line */}
                      <p className="text-xs text-ink/80 leading-relaxed">
                        {st.shortLine}
                      </p>
                    </div>

                    <div className="mt-3 pt-2 border-t border-ink/10 flex items-center justify-between text-[11px] text-muted">
                      <span>{st.note}</span>
                      <ArrowRight size={13} className="text-muted/60" />
                    </div>
                  </div>
                ))}

                {/* Final Commerce Outcome End Block */}
                <div className="p-4 rounded-xl border-2 border-ink bg-mustard flex flex-col justify-between shadow-sm text-ink hover:-translate-y-0.5 transition-transform">
                  <div>
                    <div className="flex items-center justify-between gap-1 mb-2">
                      <span className="font-mono text-xs font-bold text-ink/70 uppercase">
                        Orchestrator
                      </span>
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold uppercase tracking-wider bg-white/70 text-ink border border-ink/30">
                        Result
                      </span>
                    </div>

                    <strong className="font-serif text-lg text-ink block mb-1">
                      Final Outcome
                    </strong>

                    <p className="text-xs text-ink/90 leading-relaxed">
                      Derives CLEAN, EXCEPTION, CLAIM_RECOMMENDED, NEEDS_REVIEW, or INCOMPLETE.
                    </p>
                  </div>

                  <div className="mt-3 pt-2 border-t border-ink/20 text-[11px] font-bold text-ink/80">
                    Audit Trail Finalized
                  </div>
                </div>
              </div>
            </div>

            {/* Note on PASS / FAIL / UNCERTAIN */}
            <div className="card-signature p-6 bg-card space-y-4">
              <h3 className="font-serif text-xl font-bold text-ink">
                Verdict Semantics: Honest Truth Grounding
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="p-4 rounded-xl border-2 border-[#2E9E6B] bg-[#2E9E6B]/10">
                  <div className="flex items-center gap-2 mb-2 font-bold text-[#1B6F49]">
                    <CheckCircle2 size={18} />
                    <span>PASS</span>
                  </div>
                  <p className="text-xs text-stone-800 leading-relaxed">
                    Clear physical or photographic proof satisfies all stage rules and specifications.
                  </p>
                </div>

                <div className="p-4 rounded-xl border-2 border-[#D64545] bg-[#D64545]/10">
                  <div className="flex items-center gap-2 mb-2 font-bold text-[#A02222]">
                    <XCircle size={18} />
                    <span>FAIL</span>
                  </div>
                  <p className="text-xs text-stone-800 leading-relaxed">
                    Non-compliance, real physical damage, or PO discrepancy detected by agent checks.
                  </p>
                </div>

                <div className="p-4 rounded-xl border-2 border-[#E39A0B] bg-[#E39A0B]/15">
                  <div className="flex items-center gap-2 mb-2 font-bold text-[#9A6202]">
                    <AlertTriangle size={18} />
                    <span>UNCERTAIN</span>
                  </div>
                  <p className="text-xs text-stone-800 leading-relaxed">
                    <strong>UNCERTAIN is not a low-confidence PASS.</strong> When evidence is insufficient or photos are obstructed, the system never turns it into a pass. It halts or flags for human review.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </Band>
      </div>
    </PublicLayout>
  )
}
