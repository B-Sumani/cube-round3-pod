import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { BRAND_NAME } from '../config/brand.js'
import { getReviewQueue } from '../api/client.js'

const SessionContext = createContext(null)

const STORAGE_PREFIX = BRAND_NAME.toLowerCase()
const STORAGE_KEY_ORG = `${STORAGE_PREFIX}_session_org`
const STORAGE_KEY_OPERATOR = `${STORAGE_PREFIX}_session_operator`
const STORAGE_KEY_WORKFLOWS = `${STORAGE_PREFIX}_session_workflows`
const STORAGE_KEY_EVIDENCE = `${STORAGE_PREFIX}_session_evidence`

export function SessionProvider({ children }) {
  const [org, setOrg] = useState(() => sessionStorage.getItem(STORAGE_KEY_ORG) || 'org_demo_alpha')
  const [operator, setOperator] = useState(() => sessionStorage.getItem(STORAGE_KEY_OPERATOR) || 'Operator')

  // Review Queue state from API
  const [reviewQueue, setReviewQueue] = useState({ pending: [], resolved: [], pending_count: 0, resolved_count: 0 })
  const [reviewLoading, setReviewLoading] = useState(false)

  // Workflows executed during this session
  const [sessionWorkflows, setSessionWorkflows] = useState(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY_WORKFLOWS)
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })

  // Evidence records collected during this session: { [stage]: evidenceRecord }
  const [recentEvidenceByStage, setRecentEvidenceByStage] = useState(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY_EVIDENCE)
      return saved ? JSON.parse(saved) : {}
    } catch {
      return {}
    }
  })

  const refreshReviewQueue = useCallback(async () => {
    try {
      setReviewLoading(true)
      const data = await getReviewQueue(org)
      setReviewQueue(data || { pending: [], resolved: [], pending_count: 0, resolved_count: 0 })
    } catch (err) {
      console.warn('Could not refresh review queue:', err)
    } finally {
      setReviewLoading(false)
    }
  }, [org])

  useEffect(() => {
    refreshReviewQueue()
  }, [refreshReviewQueue])

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY_ORG, org)
    } catch (e) {
      console.warn('Could not persist org to sessionStorage', e)
    }
  }, [org])

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY_OPERATOR, operator)
    } catch (e) {
      console.warn('Could not persist operator to sessionStorage', e)
    }
  }, [operator])

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY_WORKFLOWS, JSON.stringify(sessionWorkflows))
    } catch (e) {
      console.warn('Could not persist sessionWorkflows to sessionStorage', e)
    }
  }, [sessionWorkflows])

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY_EVIDENCE, JSON.stringify(recentEvidenceByStage))
    } catch (e) {
      console.warn('Could not persist recentEvidenceByStage to sessionStorage', e)
    }
  }, [recentEvidenceByStage])

  // Continuous organisation switcher: clears all displayed workflow data
  const switchOrg = (newOrg) => {
    if (newOrg === org) return
    sessionStorage.setItem(STORAGE_KEY_ORG, newOrg)
    sessionStorage.removeItem(STORAGE_KEY_WORKFLOWS)
    sessionStorage.removeItem(STORAGE_KEY_EVIDENCE)
    setOrg(newOrg)
    setSessionWorkflows([])
    setRecentEvidenceByStage({})
  }

  // Operator name updater
  const updateOperator = (newOperator) => {
    const trimmed = newOperator
    setOperator(trimmed)
    sessionStorage.setItem(STORAGE_KEY_OPERATOR, trimmed)
  }

  const recordWorkflowRun = (workflow, evidenceBundle = {}) => {
    setSessionWorkflows((prev) => {
      const filtered = prev.filter((w) => w.workflow_id !== workflow.workflow_id)
      return [workflow, ...filtered]
    })

    // Update recent evidence by stage
    if (evidenceBundle && typeof evidenceBundle === 'object') {
      setRecentEvidenceByStage((prev) => {
        const next = { ...prev }
        Object.values(evidenceBundle).forEach((rec) => {
          if (rec && rec.stage) {
            next[rec.stage] = rec
          }
        })
        return next
      })
    }
    refreshReviewQueue()
  }

  const updateWorkflow = (updatedWorkflow, updatedBundle = {}) => {
    setSessionWorkflows((prev) => {
      const next = prev.map((w) => (w.workflow_id === updatedWorkflow.workflow_id ? updatedWorkflow : w))
      if (!next.some((w) => w.workflow_id === updatedWorkflow.workflow_id)) {
        return [updatedWorkflow, ...next]
      }
      return next
    })

    if (updatedBundle && typeof updatedBundle === 'object') {
      setRecentEvidenceByStage((prev) => {
        const next = { ...prev }
        Object.values(updatedBundle).forEach((rec) => {
          if (rec && rec.stage) {
            next[rec.stage] = rec
          }
        })
        return next
      })
    }
    refreshReviewQueue()
  }

  return (
    <SessionContext.Provider
      value={{
        org,
        operator,
        switchOrg,
        updateOperator,
        sessionWorkflows,
        recentEvidenceByStage,
        recordWorkflowRun,
        updateWorkflow,
        reviewQueue,
        pendingCount: reviewQueue?.pending_count || 0,
        resolvedCount: reviewQueue?.resolved_count || 0,
        reviewLoading,
        refreshReviewQueue,
      }}
    >
      {children}
    </SessionContext.Provider>
  )
}

export function useSession() {
  const context = useContext(SessionContext)
  if (!context) {
    throw new Error('useSession must be used within a SessionProvider')
  }
  return context
}
