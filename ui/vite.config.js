import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { BRAND_NAME } from './src/config/brand.js'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    {
      name: 'html-brand-transform',
      transformIndexHtml(html) {
        return html
          .replace(/<title>.*?<\/title>/, `<title>${BRAND_NAME}</title>`)
          .replace(
            /<text y='70' x='18' font-size='65' font-weight='bold' font-family='serif' fill='%231F1B16'>[A-Z]<\/text>/,
            `<text y='70' x='18' font-size='65' font-weight='bold' font-family='serif' fill='%231F1B16'>${BRAND_NAME.charAt(0)}</text>`
          )
      },
    },
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
