import { defineConfig } from "vite";

const backend = process.env.BACKEND_URL || "http://localhost:8000";

export default defineConfig({
  server: {
    proxy: {
      "/join": backend,
      "/ws": { target: backend, ws: true },
    },
  },
});
