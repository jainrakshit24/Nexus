"""nexus — command line entry point."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import context as context_mod
from . import discover, graph as graph_mod, scrub, tokens as tokens_mod
from .impact import analyze
from .record import CONFIDENCE, TIERS, Record
from .store import NotInitialized, Store, find_root, git_root


def _store(args) -> Store:
    root = Path(args.root).resolve() if getattr(args, "root", None) else find_root()
    store = Store(root)
    rebuilt = store.ensure_current_schema()
    if rebuilt is not None:
        print(f"index schema changed — rebuilt {rebuilt} record(s) from Markdown", file=sys.stderr)
    return store


def _warn(warnings: list[scrub.Finding]) -> None:
    for w in warnings:
        print(f"  warning: {w.pattern} ({w.excerpt}) — stored anyway, review it", file=sys.stderr)


# ---------- commands ----------

def cmd_init(args) -> int:
    target = Path(args.path).resolve()
    root = target if args.here else (git_root(target) or target)
    store = Store.init(root)

    prof = discover.profile(root)
    rec = Record(
        name="project-overview",
        type="project",
        body=discover.to_markdown(prof),
        confidence="observed",
        source=f"nexus init on {prof['path']}",
        tags=["discovery", prof["stack"].split(" ")[0]],
    )
    action, rec, warnings = store.write(rec)
    _warn(warnings)

    print(f"initialized {store.dir}")
    print(f"  project : {prof['name']} ({prof['stack']})")
    print(f"  files   : {prof['file_count']}")
    print(f"  tests   : {prof['test_command'] or 'not detected'}")
    git = prof["git"]
    if git.get("repo"):
        print(f"  git     : {git['branch']} @ {git['head']}")
    print(f"  overview: {action} -> {store.path_for(rec)}")
    return 0


def cmd_remember(args) -> int:
    store = _store(args)
    body = args.text if args.text else sys.stdin.read()
    if not body.strip():
        print("nothing to remember (empty body)", file=sys.stderr)
        return 2
    rec = Record(
        name=args.name or " ".join(body.split()[:8]),
        type=args.type,
        body=body,
        confidence=args.confidence,
        source=args.source or "",
        graph_refs=args.graph_ref or [],
        tags=args.tag or [],
    )
    try:
        action, rec, warnings = store.write(rec)
    except scrub.SecretFound as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        for f in e.findings:
            print(f"  {f.pattern}: {f.excerpt}", file=sys.stderr)
        print("  nothing was written. Store a pointer to the secret, not the secret.", file=sys.stderr)
        return 3
    _warn(warnings)
    print(f"{action}: {rec.name} [{rec.type}/{rec.confidence}] {rec.id}")
    if action == "superseded":
        print(f"  previous version kept at .nexus/superseded/ (supersedes {rec.supersedes})")
    return 0


def cmd_recall(args) -> int:
    store = _store(args)
    t0 = time.perf_counter()
    results = store.recall(" ".join(args.query), type_=args.type, limit=args.limit,
                           include_superseded=args.all)
    ms = (time.perf_counter() - t0) * 1000

    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    if not results:
        print(f"no matches ({ms:.0f} ms)")
        return 1
    for r in results:
        flag = " [superseded]" if r["superseded_by"] else ""
        src = f" — {r['source']}" if r["source"] else ""
        print(f"[{r['relevance']:5.1f}] {r['name']} ({r['type']}/{r['confidence']}){flag}{src}")
        if args.full:
            body = Path(r["path"]).read_text(encoding="utf-8").split("---", 2)[-1].strip()
            print("".join(f"        {line}\n" for line in body.splitlines()))
    sys.stdout.flush()  # keep the summary below the results when stderr is unbuffered
    print(f"{len(results)} result(s) in {ms:.0f} ms", file=sys.stderr)
    return 0


def cmd_show(args) -> int:
    store = _store(args)
    chain = store.chain(args.ident)
    if not chain:
        print(f"not found: {args.ident}", file=sys.stderr)
        return 1
    for i, r in enumerate(chain):
        label = "current" if i == 0 and not r["superseded_by"] else f"-{i}"
        print(f"=== {label} | {r['id']} | {r['confidence']} | {r['created_at']} ===")
        print(Path(r["path"]).read_text(encoding="utf-8"))
    return 0


def cmd_forget(args) -> int:
    store = _store(args)
    result = store.forget(args.ident, hard=args.hard)
    if result is None:
        print(f"not found: {args.ident}", file=sys.stderr)
        return 1
    print(f"{result}: {args.ident}")
    return 0


def cmd_reindex(args) -> int:
    store = _store(args)
    t0 = time.perf_counter()
    n = store.reindex()
    print(f"indexed {n} record(s) in {(time.perf_counter()-t0)*1000:.0f} ms")
    return 0


def cmd_status(args) -> int:
    store = _store(args)
    s = store.stats()
    if args.json:
        print(json.dumps(s, indent=2))
        return 0
    print(f"root      : {s['root']}")
    print(f"live      : {s['live']} record(s)")
    for t, n in sorted(s["by_type"].items()):
        print(f"  {t:<11}: {n}")
    print(f"superseded: {s['superseded']}")
    print(f"index     : {s['index']}")
    return 0



def cmd_impact(args) -> int:
    store = _store(args)
    imp = analyze(store.root, args.target, use_graph=not args.no_graph, depth=args.depth,
                  use_serena=args.serena)

    if args.json:
        print(json.dumps({
            "target": imp.target, "blast_radius": imp.blast_radius, "gear": imp.gear,
            "reason": imp.reason(), "graph_available": imp.graph_available,
            "staleness": imp.staleness.summary() if imp.staleness else None,
            "dependents": [{"file": d.file, "strength": d.strength, "hops": d.hops,
                            "sources": sorted(d.sources), "relations": sorted(d.relations),
                            "symbols": d.symbols_hit} for d in imp.dependents],
            "notes": imp.notes,
        }, indent=2))
        return 0

    print(f"{imp.target}  blast radius {imp.blast_radius} -> workflow: {imp.gear}")
    print(f"  reason: {imp.reason()}")
    print(f"  graph : {imp.staleness.summary() if imp.staleness else 'unavailable'}")
    for n in imp.notes:
        print(f"  note  : {n}")
    if not imp.dependents:
        print("  no dependents found")
        return 0
    print()
    for d in imp.dependents:
        rel = ", ".join(sorted(d.relations)) or "-"
        hop = f"{d.hops} hop" if d.hops else "text"
        print(f"  [{d.strength:6}] {d.file:<32} {hop:<6} via {','.join(sorted(d.sources)):<16} {rel}")
    return 0


def cmd_context(args) -> int:
    store = _store(args)
    pack = context_mod.build(store.root, " ".join(args.task), budget=args.budget)
    print(pack.render())
    acc = pack.accounting()
    if not args.no_log:
        tokens_mod.record(store.root, acc)
    for line in acc.lines():
        print(line, file=sys.stderr)
    if pack.actual > pack.budget:  # cannot happen; assert it loudly if it ever does
        print(f"BUG: pack {pack.actual} exceeds budget {pack.budget}", file=sys.stderr)
        return 5
    return 0


def cmd_tokens(args) -> int:
    store = _store(args)
    t = tokens_mod.totals(store.root)
    print(f"packs                : {t['packs']:>8,}")
    print(f"actual   (measured)  : {t['actual_measured']:>8,} tokens   [{t['tokenizer']}]")
    print(f"baseline (measured)  : {t['baseline_measured']:>8,} tokens   [full-file reads of the same files]")
    print(f"saved    (estimated) : {t['saved_estimated']:>8,} tokens   [baseline - actual; the baseline was never run]")
    usage = tokens_mod.platform_usage(store.root)
    if usage.get("available"):
        print(f"host reported usage  : {usage['input_tokens']:>8,} in / {usage['output_tokens']:,} out "
              f"[{usage['transcripts']} transcript(s)]")
    else:
        print(f"host reported usage  : unavailable   [{usage['reason']}]")
    return 0


def cmd_graph(args) -> int:
    store = _store(args)
    try:
        g = graph_mod.load(store.root)
    except graph_mod.GraphMissing as e:
        print(str(e), file=sys.stderr)
        return 6
    s = g.staleness(store.root, extensions={".py", ".js", ".ts", ".go", ".rs"})
    print(f"graph dir : {g.dir}")
    print(f"built on  : {g.graph_root}")
    print(f"size      : {len(g.nodes)} nodes, {len(g.links)} links (directed={g.directed})")
    print(f"freshness : {s.summary()}")
    for label, items in (("changed", s.changed), ("deleted", s.deleted), ("never indexed", s.unindexed)):
        for f in items[:args.limit]:
            print(f"  {label:13}: {f}")
        if len(items) > args.limit:
            print(f"  {label:13}: ... and {len(items)-args.limit} more")
    if s.is_stale:
        print("\nRebuild with `/graphify . --update` in your agent. NEXUS reads graphs; it does not build them.")
    return 0


# ---------- parser ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nexus", description="Engineering memory for a codebase.")
    p.add_argument("--root", help="project root (default: nearest .nexus/ above cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="discover this project and create .nexus/")
    i.add_argument("path", nargs="?", default=".")
    i.add_argument("--here", action="store_true", help="use this exact dir, not the git root")
    i.set_defaults(func=cmd_init)

    r = sub.add_parser("remember", help="store one fact")
    r.add_argument("text", nargs="?", help="the fact (omit to read stdin)")
    r.add_argument("--name", help="slug; defaults to the first words of the text")
    r.add_argument("--type", choices=TIERS, default="project")
    r.add_argument("--confidence", choices=CONFIDENCE, default="assumed")
    r.add_argument("--source", help="file:line, commit, or test run — required for verified")
    r.add_argument("--graph-ref", action="append", help="graph node id (repeatable)")
    r.add_argument("--tag", action="append")
    r.set_defaults(func=cmd_remember)

    q = sub.add_parser("recall", help="retrieve relevant facts")
    q.add_argument("query", nargs="*")
    q.add_argument("--type", choices=TIERS)
    q.add_argument("--limit", type=int, default=10)
    q.add_argument("--all", action="store_true", help="include superseded records")
    q.add_argument("--full", action="store_true", help="print record bodies")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_recall)

    sh = sub.add_parser("show", help="print a record and its supersede history")
    sh.add_argument("ident", help="record id or name")
    sh.set_defaults(func=cmd_show)

    f = sub.add_parser("forget", help="retire a record (kept on disk unless --hard)")
    f.add_argument("ident")
    f.add_argument("--hard", action="store_true", help="delete the file permanently")
    f.set_defaults(func=cmd_forget)

    x = sub.add_parser("reindex", help="rebuild the SQLite index from Markdown")
    x.set_defaults(func=cmd_reindex)

    im = sub.add_parser("impact", help="what else moves if this changes")
    im.add_argument("target", help="file path or symbol name")
    im.add_argument("--no-graph", action="store_true", help="text evidence only")
    im.add_argument("--depth", type=int, default=1, help="reverse-edge hops to follow (2 finds transitive breakage)")
    im.add_argument("--serena", action="store_true",
                    help="also ask the language server (Serena); accurate but costs a few seconds")
    im.add_argument("--json", action="store_true")
    im.set_defaults(func=cmd_impact)

    cx = sub.add_parser("context", help="assemble context for a task, under a token budget")
    cx.add_argument("task", nargs="+")
    cx.add_argument("--budget", type=int, default=4000)
    cx.add_argument("--no-log", action="store_true", help="do not append to the token log")
    cx.set_defaults(func=cmd_context)

    tk = sub.add_parser("tokens", help="token accounting for this project")
    tk.set_defaults(func=cmd_tokens)

    gr = sub.add_parser("graph", help="knowledge graph status and freshness")
    gr.add_argument("--limit", type=int, default=10)
    gr.set_defaults(func=cmd_graph)

    s = sub.add_parser("status", help="store summary")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except NotInitialized as e:
        print(str(e), file=sys.stderr)
        return 4
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
