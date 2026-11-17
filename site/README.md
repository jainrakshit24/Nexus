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
