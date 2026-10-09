import React from 'react'
import { Link } from 'react-router-dom'
import Band from '../components/Band'
import { BRAND_NAME } from '../config/brand.js'
import { Home, ArrowLeft } from 'lucide-react'

export default function NotFoundPage() {
  return (
    <Band color="cream" className="py-20 text-center">
      <div className="card-signature p-10 md:p-14 bg-card max-w-lg mx-auto">
        <span className="font-mono text-xs px-3 py-1 rounded-full border-2 border-ink bg-mustard font-bold text-ink uppercase tracking-wider inline-block mb-4">
          Error 404
        </span>
        <h2 className="font-serif text-3xl md:text-4xl font-bold text-ink mb-3">
          Page Not Found
        </h2>
        <p className="text-sm text-muted mb-8 leading-relaxed">
          The requested route does not exist within the {BRAND_NAME} operations platform.
        </p>
        <div className="flex justify-center gap-3">
          <Link to="/app/dashboard" className="btn-primary text-sm py-2.5 px-5 flex items-center gap-2">
            <Home size={16} />
            <span>Go to Dashboard</span>
          </Link>
        </div>
      </div>
    </Band>
  )
}
