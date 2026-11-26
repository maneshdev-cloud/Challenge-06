import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const ROOT_DIR = path.resolve(fileURLToPath(new URL(".", import.meta.url)), "..");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ROOT_DIR, "");
  const apiProxy = {
    "/api": {
      target: process.env.VITE_API_TARGET || env.VITE_API_TARGET || "http://127.0.0.1:8000",
      changeOrigin: true,
      rewrite: (reqPath) => reqPath.replace(/^\/api/, "")
    }
  };

  return {
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
      setupFiles: "./src/test/setup.js",
      testTimeout: 30000,
      coverage: {
        provider: "v8",
        reporter: ["text", "text-summary"],
        include: ["src/App.jsx", "src/api/**", "src/hooks/**", "src/utils/**", "src/components/**"],
        thresholds: {
          lines: 75,
          statements: 75,
          branches: 58,
          functions: 52
        }
      }
    },
    build: {
      target: "es2022",
      sourcemap: false,
      chunkSizeWarningLimit: 600,
      rollupOptions: {
        output: {
          manualChunks(id) {
            const p = id.replace(/\\/g, "/");
            if (
              p.includes("commonjsHelpers") ||
              p.includes("/node_modules/react/") ||
              p.includes("/node_modules/react-dom/") ||
              p.includes("/node_modules/scheduler/")
            ) {
              return "vendor";
            }
            if (p.includes("/node_modules/lucide-react/")) {
              return "icons";
            }
            if (
              p.includes("/node_modules/recharts/") ||
              p.includes("/node_modules/victory-vendor/") ||
              p.includes("/node_modules/d3-") ||
              p.includes("/node_modules/recharts-scale/") ||
              p.includes("/node_modules/react-smooth/")
            ) {
              return "charts";
            }
            return undefined;
          }
        }
      }
    }
  };
});
