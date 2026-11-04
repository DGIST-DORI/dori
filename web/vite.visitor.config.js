import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  root: 'visitor', plugins: [react()],
  build: { outDir: '../dist-visitor', emptyOutDir: true },
  server: { proxy: { '/api': 'http://127.0.0.1:3100', '/ws': { target: 'ws://127.0.0.1:3100', ws: true } } },
});
