import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Tests unitaires de la couche API (client, erreurs, lecteur SSE) : environnement Node
// (fetch, ReadableStream, TextDecoder natifs de Node 24).
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
