# NEXUS — landing page

The public product page for [NEXUS](../README.md), the local-first engineering
memory system in the parent directory.

This is a **marketing surface, not part of the tool**. Nothing here is imported
by the Python package, nothing here is required to run NEXUS, and the page ships
no analytics and calls no backend — it is static once built.

## Stack

| | |
|---|---|
| Framework | TanStack Start + React 19 |
| Build | Vite |
| Styling | Tailwind + shadcn/ui primitives |
| Icons | lucide-react |
| Tests | Vitest |

## Deploy

Pushing this branch deploys the page to GitHub Pages — `.github/workflows/pages.yml`
installs, runs the tests, renders the site to static files and publishes them.

One setting has to be flipped by hand, once: **repo → Settings → Pages → Source →
GitHub Actions**. Until that is done the workflow builds and the deploy step fails.

```bash
bun run build:static                  # what CI runs, for a custom domain or local check
BASE_PATH=/Nexus/ bun run build:static  # what CI runs for a project page
```

GitHub Pages has no server, so `scripts/prerender.mjs` boots the built server,
asks it for each route and writes the HTML out. Nitro ships a prerenderer, but on
this beta it answers 404 for a build with a custom server entry while the server
itself serves the same route fine — this is the same operation with one fewer
moving part, and it refuses to publish a route that did not render.

`BASE_PATH` exists because a project page is served from `/<repo>/`, and every
asset URL needs that prefix. It is read from the environment, not hardcoded, so
the dev server and a custom domain both get `/`.

## Develop

```bash
cd site
bun install          # or: npm install
bun run dev          # http://localhost:3000
bun run test
bun run build
```

## Where the content lives

| Path | What |
|---|---|
| `src/routes/index.tsx` | the entire landing page — every section, in order |
| `src/routes/__root.tsx` | document shell, metadata, theme |
| `src/styles.css` | design tokens, both colour themes |
| `src/components/ui/` | shadcn primitives, unmodified |

## One rule for this page

**Every number on it must come from [`docs/BENCHMARK.md`](../docs/BENCHMARK.md),
with its honesty label intact.** `saved` is *estimated* and says so; `recall@5 =
0.70` is reported against the pre-registered threshold it sits on, not rounded
up. The page also carries the caveats — a product page that hides what the tool
cannot do is a worse lie than a page with no numbers at all.

If a benchmark changes, change the page. If the page needs a number the benchmark
does not have, measure it first.

