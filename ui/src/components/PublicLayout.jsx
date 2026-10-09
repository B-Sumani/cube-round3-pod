import React from 'react'
import NavBar from './NavBar'
import { BRAND_NAME } from '../config/brand.js'

export default function PublicLayout({ children }) {
  return (
    <div className="min-h-screen flex flex-col bg-cream text-ink font-sans antialiased">
      {/* Top Bar: Exactly the same consistent NavBar */}
      <NavBar />

      {/* Main Content */}
      <main className="flex-1 w-full">
        {children}
      </main>

      {/* Charcoal Footer (no tagline) */}
      <footer className="w-full bg-charcoal text-cream border-t-2 border-ink py-8 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-[#D1CBBF]">
          <div>
            <span className="font-serif font-bold text-cream text-lg block">
              {BRAND_NAME}
            </span>
          </div>
          <div className="font-mono text-[11px] text-[#D1CBBF]">
            API Gateway: <span className="text-mustard">http://localhost:8100</span> (Proxy: <span className="text-mustard">/api</span>)
          </div>
        </div>
      </footer>
    </div>
  )
}
