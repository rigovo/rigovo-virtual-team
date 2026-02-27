import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root: resolve(__dirname, "src/renderer"),
  plugins: [react()],
  build: {
    rollupOptions: {
      input: resolve(__dirname, "src/renderer/index.html"),
    },
  },
  define: {
    // stub out Electron APIs so the renderer renders in browser
    "window.electronAPI": "undefined",
  },
});
