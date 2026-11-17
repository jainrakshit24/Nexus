import { defineConfig } from "vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import tsConfigPaths from "vite-tsconfig-paths";
import { nitro } from "nitro/vite";

// GitHub Pages serves a project site from /<repo>/, so every asset URL needs
// that prefix. It is read from the environment rather than hardcoded: the dev
// server and a custom domain both want "/", and only the Pages workflow sets it.
const base = process.env.BASE_PATH ?? "/";

export default defineConfig({
  base,
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
