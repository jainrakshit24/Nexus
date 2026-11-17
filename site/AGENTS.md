# site/ — working notes for agents

This is the public landing page for NEXUS. It is a **marketing surface, not part
of the tool**: nothing in `../nexus/` imports it, the Python test suite does not
run it, and `pyproject.toml` does not ship it.

## Stack

TanStack Start + React 19, Vite 8, Tailwind 4, shadcn/ui primitives, Vitest.
The Vite config is plain and local — every plugin is listed in `vite.config.ts`
and is a direct dependency. There is no wrapper config package.

## Where things live

| Path | What |
|---|---|
| `src/routes/index.tsx` | the whole landing page, every section in order |
| `src/routes/__root.tsx` | document shell, metadata, error and 404 boundaries |
| `src/styles.css` | design tokens, both colour themes |
| `src/components/ui/` | shadcn primitives — unmodified, do not edit |
| `src/server.ts` | SSR entry; wraps render errors so a failure shows a page |

## Rules for changing this page

1. **Every number must come from `../docs/BENCHMARK.md`, with its honesty label
   intact.** `saved` is *estimated* and must say so. `recall@5 = 0.70` is reported
   against the pre-registered threshold it sits on, never rounded up. If the page
   needs a number the benchmark does not have, measure it first.
2. **Keep the caveats on the page.** The `1.00` graph-expansion result ships with
   the sentence explaining why it is not a general accuracy claim. A product page
   that hides what the tool cannot do is worse than one with no numbers at all.
3. **No analytics, no error service, no backend.** The page is static once built
   and must stay that way. A render failure goes to the console.
4. **No third-party builder branding**, in metadata, comments, dependencies or
   markup. This page represents the project, nothing else.
5. Edit `src/routes/index.tsx` for content. Leave `src/components/ui/` alone — it
   is upstream shadcn and replacing it wholesale is cheaper than patching it.

## Commands

```bash
bun install
bun run dev      # http://localhost:8080
bun run build
bun run test
bun run lint
```
