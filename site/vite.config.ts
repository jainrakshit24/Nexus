import { defineConfig } from "vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import tsConfigPaths from "vite-tsconfig-paths";
import { nitro } from "nitro/vite";

export default defineConfig({
  plugins: [
    tsConfigPaths(),
    tailwindcss(),
    // `server: { entry: "server" }` points TanStack Start's SSR entry at
    // src/server.ts, which wraps render errors so a failure shows a page
    // instead of a blank document.
    tanstackStart({ server: { entry: "server" } }),
    viteReact(),
    nitro(),
  ],
  server: { host: true, port: 8080 },
  preview: { host: true, port: 8080 },
});
