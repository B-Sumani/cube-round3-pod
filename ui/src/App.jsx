import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { SessionProvider } from './context/SessionContext'
import AppShell from './components/AppShell'

// Pages
import HomePage from './pages/HomePage'
import DashboardPage from './pages/DashboardPage'
import ReviewPage from './pages/ReviewPage'
import AgentDetailPage from './pages/AgentDetailPage'
import NotFoundPage from './pages/NotFoundPage'

export default function App() {
  return (
    <BrowserRouter>
      <SessionProvider>
        <Routes>
          {/* Public Routes */}
          <Route path="/" element={<HomePage />} />
          <Route path="/signin" element={<Navigate to="/" replace />} />

          {/* App Shell: /app/* (directly accessible, no login required) */}
          <Route path="/app" element={<AppShell />}>
            <Route index element={<Navigate to="/app/dashboard" replace />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="review" element={<ReviewPage />} />
            <Route path="agents/:stage" element={<AgentDetailPage />} />

            {/* Redirect deleted routes to /app/dashboard */}
            <Route path="run" element={<Navigate to="/app/dashboard" replace />} />
            <Route path="agents" element={<Navigate to="/app/dashboard" replace />} />
            <Route path="evidence" element={<Navigate to="/app/dashboard" replace />} />

            <Route path="*" element={<NotFoundPage />} />
          </Route>

          {/* Fallback 404 Route */}
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </SessionProvider>
    </BrowserRouter>
  )
}
