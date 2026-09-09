import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built output goes to ../frontend/dist, which FastAPI serves. During `npm run dev`
// the API is proxied so the React app talks to the real corpus on localhost:8000.
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../frontend/dist', emptyOutDir: true },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ['/health','/stats','/subjects','/acts','/syllabus','/search','/pyq']
        .map(p => [p, { target: 'http://127.0.0.1:8000', changeOrigin: true }])
    ),
  },
})
