import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Relative "/api/..." calls from src/api.ts hit this dev server; proxy
    // them to the FastAPI backend so the same relative-URL code works
    // unchanged in both `npm run dev` and the production single-port build.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        ws: true,
      },
    },
  },
});
