import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The match room's port; override if 8000 is taken: GALLERY_API_PORT=8001 npm run dev
const api = process.env.GALLERY_API_PORT ?? "8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": `http://localhost:${api}`,
      "/ws": { target: `ws://localhost:${api}`, ws: true },
    },
  },
});
