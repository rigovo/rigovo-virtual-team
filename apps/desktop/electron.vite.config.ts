import { resolve } from "node:path";
import { defineConfig, externalizeDepsPlugin } from "electron-vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()]
  },
  preload: {
    plugins: [externalizeDepsPlugin()]
  },
  renderer: {
    root: resolve(__dirname, "src/renderer"),
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: Number(process.env.RIGOVO_DESKTOP_PORT || 5173),
      strictPort: false
    },
    build: {
      rollupOptions: {
        input: resolve(__dirname, "src/renderer/index.html")
      }
    }
  }
});
