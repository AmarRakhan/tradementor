import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const webRoot = fileURLToPath(new URL("../../", import.meta.url));

export default defineConfig({
  root: webRoot,
  plugins: [react()],
  resolve: { alias: { "@": webRoot } },
  server: { host: "127.0.0.1", port: 4174, strictPort: true },
});
