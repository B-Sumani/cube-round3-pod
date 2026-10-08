import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { BRAND_NAME } from './config/brand.js'
import './styles/index.css'

document.title = BRAND_NAME

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
