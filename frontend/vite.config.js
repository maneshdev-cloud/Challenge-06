import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxy = {
  "/api": {
    target: process.env.VITE_API_TARGET || "http://127.0.0.1:8000",
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, "")
  }
};

export default defineConfig({
  envDir: "..",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: apiProxy
  },
  preview: {
    port: 4173,
    proxy: apiProxy
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js"
  },
  build: {
    target: "es2022",
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ["recharts"],
          icons: ["lucide-react"]
        }
      }
    }
  }
});
