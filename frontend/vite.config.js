import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Receipt Ghostbuster frontend. Talks to the FastAPI backend (default :8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
});
