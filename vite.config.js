import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  root: path.resolve(__dirname, 'src/verify'),
  base: '/assets/theoskaris_einvoice/verify/',
  build: {
    outDir: path.resolve(__dirname, 'theoskaris_einvoice/public/verify'),
    emptyOutDir: true,
  },
})
