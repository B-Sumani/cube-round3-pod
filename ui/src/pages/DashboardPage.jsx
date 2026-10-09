import React from 'react'
import { Link } from 'react-router-dom'
import Band from '../components/Band'
import { AGENTS } from '../data/agents'
import { BRAND_NAME } from '../config/brand.js'
import { ArrowRight } from 'lucide-react'

export default function DashboardPage() {
  return (
    <div className="w-full space-y-0">
      <Band
        color="cream"
        title="Dashboard"
        description={`An overview of the ${BRAND_NAME} workflow and its five agents. Select an agent to work with it.`}
      >
        {/* About BRAND_NAME and its agents */}
        <div className="card-signature p-6 md:p-8 bg-card mb-8 space-y-4">
          <h3 className="font-serif text-2xl font-bold text-ink">
            About {BRAND_NAME} and Its Agents
          </h3>
          <p className="text-sm md:text-base text-ink/85 leading-relaxed">
            {BRAND_NAME} operates as one connected commerce operations workflow. Every unit advances through a sequential, policy-directed order:
            {' '}<strong>Receiving &rarr; Prep (FBA) or Pack (MFN) &rarr; Returns (if returned) &rarr; Recovery &rarr; Final Commerce Outcome</strong>.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
            <div className="p-4 rounded-xl border border-ink/20 bg-cream/40 text-xs text-ink space-y-1">
              <strong className="block text-ink text-sm font-serif">Orchestrator Authority</strong>
              <p className="text-muted leading-relaxed">
                Specialized agents return discrete judgments and content-addressed evidence records. The orchestrator owns workflow state, evaluates routing policies, and derives the final commerce outcome.
              </p>
            </div>
            <div className="p-4 rounded-xl border border-ink/20 bg-cream/40 text-xs text-ink space-y-1">
              <strong className="block text-ink text-sm font-serif">Honest Verdict Grounding</strong>
              <p className="text-muted leading-relaxed">
                PASS, FAIL, and UNCERTAIN are distinct functional verdicts. <strong>UNCERTAIN is not a low-confidence PASS</strong>; when proof is insufficient, the system halts and directs the case to the Review Queue for human decision.
              </p>
            </div>
          </div>
        </div>

        {/* Five Agent Boxes: ONE ROW on desktop, horizontally scrollable on mobile */}
        <div>
          <h4 className="text-xs font-bold uppercase tracking-wider text-muted mb-3">
            Five Stage Agents (Select to Work with an Agent)
          </h4>

          <div className="overflow-x-auto flex md:grid md:grid-cols-5 gap-3 pb-3">
            {AGENTS.map((agent) => (
              <Link
                key={agent.stage}
                to={`/app/agents/${agent.stage}`}
                className="card-signature p-4 bg-card flex flex-col justify-between transition-all hover:-translate-y-1 hover:shadow-[5px_5px_0_var(--ink)] cursor-pointer group text-left min-w-[160px] md:min-w-0 flex-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-ink"
                aria-label={`Open ${agent.name}`}
              >
                <div>
                  <span className="font-mono text-xs font-bold uppercase tracking-wider text-muted block mb-1">
                    Stage {agent.stageNumber}
                  </span>
                  <strong className="font-serif text-base font-bold text-ink block group-hover:text-ink/80">
                    {agent.name}
                  </strong>
                </div>

                <div className="mt-4 pt-2 border-t border-ink/10 flex items-center justify-end text-xs text-muted group-hover:text-ink transition-colors">
                  <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
                </div>
              </Link>
            ))}
          </div>
        </div>
      </Band>
    </div>
  )
}
