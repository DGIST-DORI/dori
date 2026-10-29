// web/vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import svgr from 'vite-plugin-svgr'

export default defineConfig({
  server: { proxy: { "/api": "http://127.0.0.1:3000", "/navigation": "http://127.0.0.1:3000" } },
  build: {
    manifest: 'manifest.json',
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id) return;

          // Keep the largest shared libraries in stable vendor chunks for cache reuse.
          if (id.includes('node_modules/react/') || id.includes('node_modules/react-dom/')) {
            return 'vendor-react';
          }
          if (id.includes('node_modules/roslib/')) {
            return 'vendor-ros';
          }
          if (id.includes('node_modules/lucide-react/')) {
            return 'vendor-icons';
          }

          // Split major dashboard domains without over-fragmenting smaller modules.
          if (id.includes('/src/panels/hri/')) {
            return 'panel-hri';
          }
          if (id.includes('/src/panels/control/')) {
            return 'panel-control';
          }
          if (id.includes('/src/panels/perception/')) {
            return 'panel-perception';
          }
          if (id.includes('/src/panels/system/')) {
            return 'panel-system';
          }
        },
      },
    },
  },
  plugins: [
    react(),
    svgr({
      svgrOptions: {
        svgoConfig: {
          plugins: [
            {
              name: 'prefixIds',
              params: {
                prefix: 'dori',
                delim: '-',
              },
            },
          ],
        },
      },
    }),
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
