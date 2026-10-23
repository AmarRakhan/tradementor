import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const webRoot = fileURLToPath(new URL("../../", import.meta.url));
const mock = fileURLToPath(new URL("./markets-v644-cloud-client.ts", import.meta.url));

// The REAL Markets page + flip chart; only lib/cloud-client (Firebase + network) is faked.
export default defineConfig({
  root: webRoot,
  plugins: [react()],
  resolve: { alias: [{ find: /^@\/lib\/cloud-client$/, replacement: mock }, { find: "@", replacement: webRoot }] },
  server: { host: "127.0.0.1", port: 4176, strictPort: true },
});
