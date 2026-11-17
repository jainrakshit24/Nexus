// Render the site to static files for GitHub Pages, which has no server.
//
// Nitro ships a prerenderer, but on this beta it answers 404 for a build that
// uses a custom server entry, while the built server itself serves the same
// route fine. So this asks that server for each page instead of guessing why.
// It is the same operation, with one fewer moving part.
import { spawn } from "node:child_process";
import { cp, mkdir, readdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

const ROUTES = ["/"];
const PORT = Number(process.env.PRERENDER_PORT ?? 8791);
const OUT = "dist-static";
const BASE = (process.env.BASE_PATH ?? "/").replace(/\/+$/, "");

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function serverIsUp() {
  try {
    const res = await fetch(`http://127.0.0.1:${PORT}/`, { redirect: "manual" });
    return res.status > 0;
  } catch {
    return false;
  }
}

const server = spawn(process.execPath, [".output/server/index.mjs"], {
  env: { ...process.env, PORT: String(PORT), HOST: "127.0.0.1" },
  stdio: ["ignore", "pipe", "inherit"],
});
server.stdout.on("data", () => {});

let ready = false;
for (let i = 0; i < 60 && !ready; i++) {
  await wait(250);
  ready = await serverIsUp();
}
if (!ready) {
  server.kill();
  throw new Error(`the built server never answered on :${PORT}`);
}

try {
  await rm(OUT, { recursive: true, force: true });
  await mkdir(OUT, { recursive: true });

  // Everything vite emitted: assets, icons, robots.txt.
  for (const entry of await readdir(".output/public")) {
    await cp(join(".output/public", entry), join(OUT, entry), { recursive: true });
  }

  for (const route of ROUTES) {
    const res = await fetch(`http://127.0.0.1:${PORT}${route}`);
    if (!res.ok) throw new Error(`${route} rendered ${res.status}, refusing to publish it`);
    const html = await res.text();
    if (!html.includes("</html>")) throw new Error(`${route} returned a truncated document`);

    const file = route === "/" ? "index.html" : `${route.replace(/^\//, "")}/index.html`;
    await mkdir(join(OUT, file, ".."), { recursive: true });
    await writeFile(join(OUT, file), html, "utf8");
    console.log(`rendered ${route} -> ${OUT}/${file}  (${html.length.toLocaleString()} bytes)`);

    // Pages serves 404.html for any unknown path; the router takes it from there.
    if (route === "/") await writeFile(join(OUT, "404.html"), html, "utf8");
  }

  // Without this, Pages runs Jekyll and drops every directory starting with _.
  await writeFile(join(OUT, ".nojekyll"), "", "utf8");
  console.log(`base path: ${BASE || "/"}`);
} finally {
  server.kill();
}
