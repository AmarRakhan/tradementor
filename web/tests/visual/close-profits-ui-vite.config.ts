import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const webRoot = fileURLToPath(new URL("../../", import.meta.url));
const mock = fileURLToPath(new URL("./close-profits-ui-cloud-client.ts", import.meta.url));

// The REAL AsterRecentTrades component; only lib/cloud-client (Firebase auth + network) is replaced by an in-page fake.
export default defineConfig({
  root: webRoot,
  plugins: [react()],
  resolve: { alias: [{ find: /^@\/lib\/cloud-client$/, replacement: mock }, { find: "@", replacement: webRoot }] },
  server: { host: "127.0.0.1", port: 4175, strictPort: true },
});
