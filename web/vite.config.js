// web/vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import svgr from 'vite-plugin-svgr'

export default defineConfig({
  plugins: [
    react(),
    svgr(),
    {
      name: 'strip-roslib-cdn',
      transform(code, id) {
        if (id.includes('roslib') && code.includes('cdnjs.cloudflare.com')) {
          return code.replace(
            /var script\s*=[\s\S]*?cdnjs\.cloudflare\.com[\s\S]*?document\.head\.appendChild[\s\S]*?;/g,
            ''
          );
        }
      }
    }
  ],
})
