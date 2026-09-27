import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    proxy: {
      "/api": loadEnv(mode, ".", "PODCAST_API_URL").PODCAST_API_URL || "http://127.0.0.1:18000",
    },
  },
}));
