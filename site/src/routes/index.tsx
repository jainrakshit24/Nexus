import { useEffect, useRef, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import {
  ArrowDown,
  ArrowRight,
  Check,
  Copy,
  GitBranch,
  GitCommitHorizontal,
  Layers3,
  LockKeyhole,
  Network,
  Search,
  ShieldCheck,
  Terminal,
  Workflow,
} from "lucide-react";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "NEXUS — Local-first memory for coding agents" },
      {
        name: "description",
        content:
          "Durable project memory, import-graph impact analysis, and evidence-backed checks for coding agents. Local-first. No model calls.",
      },
      { property: "og:title", content: "NEXUS — Local-first memory for coding agents" },
      {
        property: "og:description",
        content: "Your codebase remembers. Your agent stops re-learning it.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [
      { rel: "preconnect", href: "https://fonts.googleapis.com" },
      { rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "anonymous" },
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap",
      },
    ],
  }),
  component: NexusPage,
});

const installCommands = {
  "skills.sh": "npx skills add jainrakshit24/nexus",
  "Claude Code": "/plugin marketplace add jainrakshit24/nexus",
  pip: 'pip install "nexus-eims @ git+https://github.com/jainrakshit24/nexus.git"',
};
type InstallTab = keyof typeof installCommands;

const workflowSteps = [
  {
    name: "RECALL",
    title: "Ask what's already known.",
    description: "Before grepping, before reading. A verified fact costs 30 tokens.",
    command: 'nexus recall "auth token refresh"',
    output: [
      "[100.0] refresh-tokens-are-single-use  (project/verified)",
      "        — src/auth/session.py:4",
      "[ 86.4] refresh-failures-fall-through-to-re-login  (project/verified)",
      "        — src/auth/middleware.py:5",
      "[ 71.2] the-15-minute-window-predates-mobile  (project/observed)",
      "",
      "3 result(s) in 2 ms",
    ],
  },
  {
    name: "PLAN",
    title: "Find the blast radius.",
    description: "Dependents, risks, owning role, missing ADR.",
    command: "nexus plan src/auth/session.py",
    output: [
      "# Plan 20261117T043054",
      "",
      "**Targets:** src/auth/session.py",
      "**Workflow:** full   (target path matches a risky pattern)",
      "**Blast radius:** 4",
      "",
      "## Roles",
      "- developer — every change needs one",
      "- security  — touches authentication, secrets or input handling",
      "- qa        — 4 dependent(s) can break",
      "",
      "## Dependents that must keep working",
      "- src/auth/middleware.py · src/api/refresh.py · tests/test_session.py",
      "",
      "## What we already know",
      "- refresh-tokens-are-single-use [verified]",
    ],
  },
  {
    name: "VERIFY",
    title: "Run the checks.",
    description: "Diff, secrets, lint, types, vulnerabilities, API breaks, tests.",
    command: "nexus verify",
    output: [
      "# Post-edit gate: FAIL",
      "",
      "## Breaking API changes (1)",
      "- rotate_token — parameter removed or renamed:",
      "  before: rotate_token(token, grace=...)   after: rotate_token(tok)",
      "",
      "## Tests",
      "`pytest` PASSED in 0.3s",
      "",
      "## Static checks",
      "- lint: `ruff check .` FAILED (exit 1) in 0.4s",
      "- types: NOT RUN — no types tool is configured for this project",
      "- vulnerabilities: NOT RUN — no tool is configured",
    ],
  },
  {
    name: "REMEMBER",
    title: "Write down what you learned.",
    description: "Anchored to a file, graded verified / observed / assumed.",
    command:
      'nexus remember "refresh tokens are single-use; reuse revokes the family" --confidence verified --source src/auth/session.py:142',
    output: [
      "created: refresh-tokens-are-single-use  [project/verified]",
      "         mem_01M7KWAQDP7DQPJE35V0",
      "",
      "anchored to src/auth/session.py — this fact is marked stale",
      "the moment that file's contents change.",
    ],
  },
];

const capabilities = [
  { icon: Search, command: "nexus recall", title: "Memory that survives the session.", body: "Confidence-graded facts in Markdown, retrieved by keyword and by graph." },
  { icon: GitBranch, command: "nexus impact", title: "Know what breaks first.", body: "Parsed import edges across graph, text, tests, and optionally a language server." },
  { icon: Layers3, command: "nexus context", title: "Packed, not pasted.", body: "A brief under a hard token budget instead of whole files." },
  { icon: ShieldCheck, command: "nexus verify", title: "Evidence, not assertions.", body: "Lint, types, vulnerabilities, API-shape diff, and the tests actually running." },
  { icon: Workflow, command: "nexus serve", title: "Five MCP tools.", body: "Claude Code, Cursor, Codex, VS Code. One command to wire it up." },
  { icon: Terminal, command: "nexus dashboard", title: "Watch it for free.", body: "127.0.0.1 only, unreachable from the MCP server, zero agent tokens. Enforced by a test." },
];

const limits = [
  ["LANGUAGE", "Breaking-change detection parses Python only. Other languages get the diff and the tests."],
  ["STALENESS", "Graph freshness is by mtime, not content hash. A touched-but-unchanged file reads as stale. False-stale is the safe direction."],
  ["DEAD CODE", "Counts text occurrences, so it is blind to dynamic access. Treat a hit as a question, not a verdict."],
  ["BENCHMARKS", "Every number here is synthetic and self-authored. Weak evidence by construction. A floor and a direction, not a measurement of your repo."],
  ["SCALE", "Not yet run against a large third-party codebase. Only against itself and fixtures."],
  ["UNTRUSTED REPOS", "A cloned project's .nexus/ was written by whoever wrote the project, and it enters your agent's context at session start. NEXUS fences and labels that block, but read .nexus/ before trusting a clone — the same way you would read its Makefile."],
  ["EMBEDDINGS", 'Considered and declined at recall@5 = 0.70 against a pre-registered trigger of "below 0.70". The threshold was set before the data and was not moved after.'],
];

const REPO = "https://github.com/jainrakshit24/nexus";
const BLOB = `${REPO}/blob/main`;

const docGroups = [
  {
    heading: "Start here",
    note: "What it is, what it measured, and where it runs.",
    items: [
      ["Blueprint", "docs/BLUEPRINT.md", `${BLOB}/docs/BLUEPRINT.md`,
       "Architecture, the five memory tiers and their lifecycle, the storage decision, the security model, and the token-accounting rules — including the upgrade trigger written down before the data arrived."],
      ["Benchmarks", "docs/BENCHMARK.md", `${BLOB}/docs/BENCHMARK.md`,
       "Every number on this page, with the command that produced it and a paragraph on how to read it honestly. Includes the section titled “what these numbers are not.”"],
      ["Compatibility", "docs/COMPATIBILITY.md", `${BLOB}/docs/COMPATIBILITY.md`,
       "Host support, row by row. Each one says tested or untested — one of four MCP hosts has actually been handshaken, and the table says so rather than implying four."],
    ],
  },
  {
    heading: "Decisions",
    note: "Two records, both of which argue against building more.",
    items: [
      ["ADR 0001 — Reuse over build", "docs/adr/0001", `${BLOB}/docs/adr/0001-reuse-over-build.md`,
       "Most of NEXUS already existed as mature tools. This records the decision to build only the join nobody had, and to reject Mem0, Letta and claude-mem with the reasoning for each."],
      ["ADR 0002 — Embeddings declined", "docs/adr/0002", `${BLOB}/docs/adr/0002-defer-local-embeddings-the-pre-registered-trigger-did-not-fire.md`,
       "recall@5 landed at 0.70 against a trigger of “below 0.70”, pre-registered before the benchmark ran. The threshold was not moved afterwards. The reopening conditions are listed."],
    ],
  },
  {
    heading: "Build log",
    note: "Six phases, each recording what failed before it worked.",
    items: [
      ["Phase 1 — Foundation & Memory", "docs/PHASE1.md", `${BLOB}/docs/PHASE1.md`,
       "The store, the record format, scrubbing, discovery. Shipped with an unstable recall order that had to be fixed with an id tiebreaker."],
      ["Phase 2 — Understanding & Impact", "docs/PHASE2.md", `${BLOB}/docs/PHASE2.md`,
       "The graph join and blast radius. Two deliverables were scoped down here because a dependency could not do what the plan assumed."],
      ["Phase 3 — Discipline & Security", "docs/PHASE3.md", `${BLOB}/docs/PHASE3.md`,
       "The gates. Where NEXUS stopped only knowing things and started refusing careless ones."],
      ["Phase 4 — Surfaces & Proof", "docs/PHASE4.md", `${BLOB}/docs/PHASE4.md`,
       "MCP server, host adapters, hooks, dashboard. The handshake failed first because the server invented a protocol version instead of echoing the client's."],
      ["Phase 5 — Retrieval & Memory Integrity", "docs/PHASE5.md", `${BLOB}/docs/PHASE5.md`,
       "Graph expansion in retrieval — the half of the blueprint that had never been built — plus staleness and consolidation."],
      ["Phase 6 — Deeper Verification", "docs/PHASE6.md", `${BLOB}/docs/PHASE6.md`,
       "Lint, types, vulnerabilities, breaking-change detection. Also where a self-audit found a command injection in NEXUS's own test runner, and fixed it."],
      ["Research", "docs/RESEARCH.md", `${BLOB}/docs/RESEARCH.md`,
       "What already existed before any code was written: the tools, their licences, and the reuse-versus-build call for each."],
      ["Phase plan", "docs/PHASES.md", `${BLOB}/docs/PHASES.md`,
       "The plan and its acceptance criteria. The brief suggested ten phases; this collapsed them to four, and says why."],
    ],
  },
];

const mechanics = [
  {
    index: "01",
    title: "Why Markdown is the truth and SQLite is not",
    body: "A fact is one file with YAML front matter and a sentence. That means a change to what the project believes shows up in `git diff` and gets reviewed in a pull request like any other change. Make the database the truth instead and memory becomes a binary nobody can read, review or merge. The index exists only because FTS5 is faster than grep — delete `.nexus/index.db`, run `nexus reindex`, and nothing is lost.",
    foot: "Rejected for this reason: Mem0, Letta, claude-mem — each owns the store, and two of them own the agent loop as well.",
  },
  {
    index: "02",
    title: "How a fact dies",
    body: "Nothing is overwritten and nothing is deleted. A contradicting fact supersedes the old one, which moves to `.nexus/superseded/` and stays readable — history is the point. Separately, a fact recorded with `--source src/auth/session.py:4` stores a hash of that file's contents. When the hash stops matching, retrieval says so out loud rather than serving a fact whose ground has moved.",
    foot: "A fact graded `observed` or `assumed` never claims currency in the first place, so it is never marked stale.",
  },
  {
    index: "03",
    title: "Why impact is a union, not a lookup",
    body: "Four sources answer “what else breaks”, because each one is blind where another sees. The import graph misses dynamic dispatch. A language server misses references that are not code — SQL, config, templates. Text search finds those and over-matches on comments. Test files tie a change to the thing that proves it. NEXUS unions all four and labels which source found what, so a weak hit never reads like a parsed one.",
    foot: "Measured against grep on the same target: grep found 4 files, NEXUS found 7, and dropped grep's one false positive — a match inside a comment.",
  },
  {
    index: "04",
    title: "Five tiers, one store",
    body: "Global facts are conventions that follow you between projects and live in `~/.nexus/global/`. Project facts are the stack, the architecture, the known bugs. Episodic records are what happened in a session and decay — `nexus consolidate` folds them into monthly summaries. Semantic facts are reusable and graph-linked. Procedural records are how to build, test and run the thing. One index spans all five, so a single recall reaches every tier at once.",
    foot: "All of it is plain Markdown under `.nexus/`, except the global tier, which is shared across every repository on the machine.",
  },
];

function ConstellationMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <path d="M5 7.5 13.5 4l9 5-1 10-8 5-9-5 0.5-11.5ZM5 7.5l8.5 8 9-6.5m-9 6.5 0 8m-8-13 8 5" />
      <circle cx="5" cy="7.5" r="1.6" /><circle cx="13.5" cy="4" r="1.6" />
      <circle cx="22.5" cy="9" r="1.6" /><circle cx="21.5" cy="19" r="1.6" />
      <circle cx="13.5" cy="24" r="1.6" /><circle cx="4.5" cy="19" r="1.6" />
      <circle cx="13.5" cy="15.5" r="1.6" />
    </svg>
  );
}

function GraphCanvas({ className = "" }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const parent = canvas.parentElement;
    if (!parent) return;
    const points = Array.from({ length: 38 }, (_, i) => {
      const angle = i * 2.399;
      const radius = 0.12 + Math.sqrt(i / 38) * 0.35;
      return {
        x: 0.5 + Math.cos(angle) * radius * 0.92,
        y: 0.5 + Math.sin(angle) * radius * 0.72,
        hub: i % 9 === 0,
        phase: i * 0.83,
      };
    });
    const edges: [number, number][] = [];
    points.forEach((point, index) => {
      const nearest = points
        .map((other, otherIndex) => ({ otherIndex, d: Math.hypot(point.x - other.x, point.y - other.y) }))
        .filter(({ otherIndex }) => otherIndex !== index)
        .sort((a, b) => a.d - b.d)
        .slice(0, index % 3 === 0 ? 3 : 2);
      nearest.forEach(({ otherIndex }) => {
        if (index < otherIndex) edges.push([index, otherIndex]);
      });
    });
    let width = 0;
    let height = 0;
    let frame = 0;
    let active = false;
    let pointerX = 0;
    let pointerY = 0;
    let smoothX = 0;
    let smoothY = 0;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const resize = () => {
      const rect = parent.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const draw = (time: number) => {
      if (!active || document.hidden) {
        frame = 0;
        return;
      }
      ctx.clearRect(0, 0, width, height);
      const t = reducedMotion ? 0 : time * 0.00028;
      if (!reducedMotion) {
        smoothX += (pointerX - smoothX) * 0.04;
        smoothY += (pointerY - smoothY) * 0.04;
      }
      const coords = points.map((p) => ({
        x: p.x * width + Math.sin(t + p.phase) * 5 + smoothX * (p.x - 0.5),
        y: p.y * height + Math.cos(t + p.phase) * 5 + smoothY * (p.y - 0.5),
      }));
      edges.forEach(([a, b], index) => {
        const p = coords[a];
        const q = coords[b];
        if (!p || !q) return;
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.quadraticCurveTo((p.x + q.x) / 2 + Math.sin(index) * 9, (p.y + q.y) / 2, q.x, q.y);
        ctx.strokeStyle = getComputedStyle(canvas).getPropertyValue("--graph-edge").trim();
        ctx.globalAlpha = 0.62;
        ctx.lineWidth = 1;
        ctx.stroke();
      });
      const pulse = reducedMotion ? -1 : Math.floor(time / 2200) % Math.max(edges.length, 1);
      const progress = reducedMotion ? 0 : (time % 2200) / 2200;
      edges.forEach(([a, b], index) => {
        const p = coords[a];
        const q = coords[b];
        if (!p || !q) return;
        if (index === pulse) {
          ctx.beginPath();
          ctx.arc(p.x + (q.x - p.x) * progress, p.y + (q.y - p.y) * progress, 2.8, 0, Math.PI * 2);
          ctx.fillStyle = getComputedStyle(canvas).getPropertyValue("--graph-pulse").trim();
          ctx.globalAlpha = Math.sin(progress * Math.PI) * 0.9;
          ctx.fill();
        }
      });
      points.forEach((point, index) => {
        const p = coords[index];
        if (!p) return;
        ctx.beginPath();
        ctx.arc(p.x, p.y, point.hub ? 4 : 2.2, 0, Math.PI * 2);
        ctx.fillStyle = getComputedStyle(canvas)
          .getPropertyValue(point.hub ? "--graph-hub" : "--graph-node")
          .trim();
        ctx.globalAlpha = point.hub ? 0.92 : 0.64;
        ctx.fill();
      });
      ctx.globalAlpha = 1;
      if (!reducedMotion) frame = requestAnimationFrame(draw);
    };
    const start = () => {
      active = true;
      if (!frame) frame = requestAnimationFrame(draw);
    };
    const stop = () => {
      active = false;
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
    };
    const visibility = () => (document.hidden ? stop() : start());
    const observer = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting) start();
      else stop();
    });
    observer.observe(canvas);
    const onPointer = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      pointerX = ((event.clientX - rect.left) / rect.width - 0.5) * 28;
      pointerY = ((event.clientY - rect.top) / rect.height - 0.5) * 28;
    };
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(parent);
    parent.addEventListener("pointermove", onPointer);
    document.addEventListener("visibilitychange", visibility);
    if (reducedMotion) start();
    return () => {
      stop();
      observer.disconnect();
      resizeObserver.disconnect();
      parent.removeEventListener("pointermove", onPointer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  return <canvas ref={canvasRef} className={`graph-canvas ${className}`} aria-hidden="true" />;
}

function CopyCommand({ command, label = "Copy command" }: { command: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };
  return (
    <Button variant="outline" className="copy-command" onClick={copy} aria-label={label}>
      <code><span className="command-prompt">$</span>{command}</code>
      {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      <span className="sr-only" aria-live="polite">{copied ? "Copied to clipboard" : ""}</span>
    </Button>
  );
}

function NexusPage() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [installTab, setInstallTab] = useState<InstallTab>("skills.sh");
  const [benchmark, setBenchmark] = useState(0);
  const [activeStep, setActiveStep] = useState(0);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const stored = window.localStorage.getItem("nexus-theme");
    const savedTheme = stored === "light" ? "light" : "dark";
    setTheme(savedTheme);
    document.documentElement.dataset["theme"] = savedTheme;
    const revealObserver = new IntersectionObserver(
      (entries, observer) => entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      }),
      { rootMargin: "0px 0px -15% 0px" },
    );
    document.querySelectorAll("[data-reveal]").forEach((element) => revealObserver.observe(element));
    const stepObserver = new IntersectionObserver(
      (entries) => entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const index = Number((entry.target as HTMLElement).dataset["stepIndex"]);
          if (Number.isFinite(index)) setActiveStep(index);
        }
      }),
      { rootMargin: "-42% 0px -42% 0px" },
    );
    document.querySelectorAll("[data-step-index]").forEach((element) => stepObserver.observe(element));
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => {
      revealObserver.disconnect();
      stepObserver.disconnect();
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset["theme"] = next;
    window.localStorage.setItem("nexus-theme", next);
  };

  return (
    <div className="site-shell" data-scrolled={scrolled}>
      <header className="site-header">
        <nav className="nav-wrap" aria-label="Main navigation">
          <a href="#top" className="brand" aria-label="NEXUS home"><ConstellationMark /><span>NEXUS</span></a>
          <div className="nav-links">
            <a href="#docs">Docs</a><a href="#proof">Benchmarks</a>
            <a href="https://github.com/jainrakshit24/nexus" target="_blank" rel="noreferrer">GitHub <span className="repo-badge">MIT</span></a>
            <Button variant="ghost" size="icon" className="theme-toggle" onClick={toggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
              <span aria-hidden="true">{theme === "dark" ? "◐" : "◑"}</span>
            </Button>
            <Button asChild variant="default" size="sm" className="nav-install"><a href="#install">Install <ArrowRight aria-hidden="true" /></a></Button>
          </div>
        </nav>
      </header>

      <main id="top">
        <section className="hero section-wrap" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="eyebrow hero-eyebrow">— LOCAL-FIRST · NO MODEL CALLS · MIT</p>
            <h1 id="hero-title"><span>Your codebase remembers.</span><span>Your agent stops re-learning it.</span></h1>
            <p className="hero-sub">Durable project memory, real blast-radius analysis before an edit, and a gate that runs the checks instead of claiming they passed. Nothing leaves your machine.</p>
            <div className="hero-install">
              <div className="install-tabs" role="tablist" aria-label="Installation method">
                {(Object.keys(installCommands) as InstallTab[]).map((tab) => (
                  <button role="tab" aria-selected={installTab === tab} className={installTab === tab ? "is-active" : ""} key={tab} onClick={() => setInstallTab(tab)}>{tab}</button>
                ))}
              </div>
              <CopyCommand command={installCommands[installTab]} />
              <a className="text-link hero-github" href="https://github.com/jainrakshit24/nexus" target="_blank" rel="noreferrer">View on GitHub <ArrowRight aria-hidden="true" /></a>
            </div>
            <div className="hero-stats" aria-label="Project facts"><span>0 model calls</span><i>·</i><span>44 ms cold start</span><i>·</i><span>Python 3.10+</span></div>
          </div>
          <div className="hero-visual" aria-label="A live graph of connected project knowledge">
            <GraphCanvas />
            <span className="graph-label graph-label-a">store.py</span><span className="graph-label graph-label-b">billing.py</span>
            <span className="graph-label graph-label-c">webhooks.py</span><span className="graph-label graph-label-d">ADR-0002</span>
            <div className="graph-caption"><span className="status-dot" /> import graph <span>·</span> confidence-graded memory</div>
          </div>
          <a href="#problem" className="scroll-cue" aria-label="Scroll to learn more"><span /> <small>SCROLL</small></a>
        </section>

        <section id="problem" className="problem-section section-band">
          <div className="section-wrap">
            <p className="eyebrow" data-reveal>— 01 / THE PROBLEM</p>
            <h2 className="problem-title" data-reveal>Every session starts from zero.<br /><span>The agent re-reads the same files, re-derives the same constraints, and re-makes a decision your team settled six months ago.</span></h2>
            <div className="problem-grid">
              {[
                ["CONTEXT", "It reads everything.", "9,000 tokens to answer a question worth 900."],
                ["BLINDNESS", "It edits without looking.", "Four other modules depended on that file."],
                ["TRUST", "It says the tests pass.", "It never ran them."],
              ].map(([label, title, body], index) => <article className="problem-item" data-reveal style={{ "--reveal-index": index } as React.CSSProperties} key={label}><p className="eyebrow">{label}</p><h3>{title}</h3><p>{body}</p></article>)}
            </div>
          </div>
        </section>

        <section id="loop" className="loop-section section-wrap">
          <p className="eyebrow" data-reveal>— 02 / THE LOOP</p>
          <div className="loop-layout">
            <div className="step-list">
              {workflowSteps.map((step, index) => <article key={step.name} data-step-index={index} className={`workflow-step ${activeStep === index ? "is-active" : ""}`}>
                <div className="step-heading"><span>0{index + 1}</span><h3>{step.name}</h3></div><p className="step-title">{step.title}</p><p className="step-description">{step.description}</p>
                <div className="mobile-terminal"><TerminalPanel step={step} /></div>
              </article>)}
            </div>
            <div className="terminal-sticky">{workflowSteps[activeStep] ? <TerminalPanel step={workflowSteps[activeStep]} key={activeStep} /> : null}</div>
          </div>
        </section>

        <section id="proof" className="proof-section section-band">
          <div className="section-wrap">
            <p className="eyebrow" data-reveal>— 03 / MEASURED</p><h2 data-reveal>Numbers, with the command that produced them.</h2>
            <div className="proof-grid">
              <article className="proof-panel token-panel" data-reveal>
                <div className="panel-heading"><span className="panel-index">A</span><h3>Context packing</h3></div>
                <div className="benchmark-tabs" role="tablist" aria-label="Context packing example">
                  {["refactor record module", "add a CLI flag", "speed up recall"].map((name, index) => <button key={name} role="tab" aria-selected={benchmark === index} className={benchmark === index ? "is-active" : ""} onClick={() => setBenchmark(index)}>{name}</button>)}
                </div>
                <div className="bar-chart" key={benchmark}>
                  <div className="bar-row"><span>Reading files whole</span><div className="bar-track"><div className="bar-fill bar-warm" /></div><code>{["9,122", "4,747", "10,024"][benchmark]}</code></div>
                  <div className="bar-row"><span>NEXUS context</span><div className="bar-track"><div className="bar-fill bar-blue" /></div><code>{["916", "506", "940"][benchmark]}</code></div>
                </div>
                <p className="proof-caption">nexus context "{["refactor nexus/record.py to support tags", "add a flag to nexus/cli.py", "speed up nexus/store.py recall"][benchmark]}" --budget 4000 · counted with cl100k_base</p>
              </article>
              <article className="proof-panel graph-proof" data-reveal>
                <div className="panel-heading"><span className="panel-index">B</span><h3>Graph expansion</h3></div>
                <div className="score-row"><span>keyword only</span><strong className="warm-value">0.00</strong></div><div className="score-row score-highlight"><span>keyword + graph</span><strong>1.00</strong></div>
                <p className="proof-caption">Questions only the graph can answer · recall@1</p>
                <p className="honesty-line"><strong>1.00 is not a general accuracy claim.</strong> One fact per file, asked one hop away. What it proves is the direction: a class of question keyword search answers zero times, the graph answers.</p>
              </article>
              <article className="proof-panel impact-proof" data-reveal>
                <div className="panel-heading"><span className="panel-index">C</span><h3>Impact vs grep</h3></div>
                <div className="file-columns">
                  <div><p className="file-heading">grep · 4 files</p><ul><li>session.py</li><li>middleware.py</li><li>api/login.py</li><li className="false-positive"><s>comments.md</s><small>false positive — matched a comment</small></li></ul></div>
                  <div><p className="file-heading">nexus · 7 files</p><ul><li>session.py</li><li>middleware.py</li><li>api/login.py</li><li>api/refresh.py <small>+ transitive</small></li><li>tasks/cleanup.py <small>+ transitive</small></li><li>tests/test_session.py <small>+ transitive</small></li></ul></div>
                </div>
              </article>
            </div>
            <article className="proof-panel surface-panel" data-reveal>
              <div className="panel-heading"><span className="panel-index">D</span><h3>Where the numbers show up</h3></div>
              <pre className="status-line-sample"><code>nexus · mem 42 · graph 628 · full:developer,security · saved~28,045 · 3 dirty</code></pre>
              <ul className="surface-list">
                <li><span>Status line</span><p>Under the chat input, continuously. Registered by <code>nexus install claude-code</code>.</p></li>
                <li><span>Session start</span><p>In the conversation: the running saved total, every new session.</p></li>
                <li><span>Every pack</span><p>The full actual / baseline / saved breakdown, inline with the result.</p></li>
              </ul>
              <p className="proof-caption">You never have to run a command to see what you saved.</p>
            </article>
            <div className="measured-strip" data-reveal><span>10,101 files</span><i>·</i><span>101 ms discovery</span><i>·</i><span>44 ms MCP init</span><i>·</i><span>318 ms impact, no graph</span></div>
          </div>
        </section>

        <section id="architecture" className="architecture-section section-wrap">
          <p className="eyebrow" data-reveal>— 04 / HOW IT WORKS</p><h2 data-reveal>Markdown is the truth. The index is a cache.</h2>
          <div className="architecture-layout">
            <div className="architecture-diagram" aria-label="NEXUS architecture: Markdown facts feed a rebuildable SQLite index and code graph through keyword recall and graph expansion">
              <div className="arch-node arch-truth" data-reveal><code>.nexus/*.md</code><span>the truth · Git-friendly, diffable, human-readable</span></div>
              <div className="arch-connector" aria-hidden="true"><span /></div>
              <div className="arch-node arch-index" data-reveal><code>SQLite FTS5 index</code><span>a cache · delete it, reindex, lose nothing</span></div>
              <div className="arch-branches"><div className="arch-branch" data-reveal><span className="branch-line" /><code>keyword recall</code></div><div className="arch-branch accent-branch" data-reveal><span className="branch-line" /><code>graph expansion <b>the join</b></code></div></div>
              <div className="arch-connector graph-connector" aria-hidden="true"><span /></div>
              <div className="arch-node arch-graph" data-reveal><code>code graph</code><span>NEXUS reads graphs. It does not build them.</span></div>
            </div>
            <div className="architecture-copy" data-reveal><h3>The join is the point.</h3><p>Keyword search answers <em>"what did we say about auth."</em> Graph expansion answers <em>"what do we know about the code this file depends on"</em> — a question with no shared vocabulary at all. Anchor a fact to a file and it becomes reachable through the import graph, and goes stale on its own when that file changes.</p></div>
          </div>

          <div className="worked-example" data-reveal>
            <p className="worked-label">A question keyword search cannot answer</p>
            <dl className="worked-rows">
              <div><dt>You ask</dt><dd><q>is it safe to shorten the rotation window?</q></dd></div>
              <div><dt>The fact</dt><dd>“refresh tokens are single-use; reuse revokes the family”<br /><small>anchored to <code>src/auth/session.py</code></small></dd></div>
              <div className="worked-fail"><dt>Keyword</dt><dd><strong>no match.</strong> Not one word of the question appears in the fact.</dd></div>
              <div className="worked-win"><dt>+ Graph</dt><dd><strong>found it.</strong> The question names the file; the file is where that fact was verified; the graph walks from one to the other.</dd></div>
            </dl>
            <p className="worked-caption">On a benchmark built entirely from questions of this shape, keyword search scores <b>0.00</b> and keyword + graph scores <b>1.00</b> — a direction, not an accuracy claim. The caveat is in <a href="https://github.com/jainrakshit24/nexus/blob/main/docs/BENCHMARK.md" target="_blank" rel="noreferrer">docs/BENCHMARK.md</a>.</p>
          </div>

          <div className="mechanics">
            {mechanics.map(({ index, title, body, foot }, i) => (
              <article key={index} className="mechanic" data-reveal style={{ "--reveal-index": i } as React.CSSProperties}>
                <span className="mechanic-index">{index}</span>
                <div>
                  <h3>{title}</h3>
                  <p>{body}</p>
                  <p className="mechanic-foot">{foot}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="invariant-section section-band">
          <div className="invariant-inner" data-reveal><p className="eyebrow">— 05 / THE INVARIANT</p><h2>A pass with no captured evidence is not a pass.</h2><pre><code><span className="code-keyword">if</span> self.exit_code == 0 <span className="code-keyword">and</span> <span className="code-keyword">not</span> self.log.strip():<br />    <span className="code-keyword">raise</span> ValueError(<span className="code-string">"refusing to record a passing check with no captured output"</span>)</code></pre><p className="invariant-note">It is structurally impossible to construct a passing result without the output that proves it. “Configured but not installed” is reported as a broken setup, never as a pass.</p></div>
        </section>

        <section className="capabilities-section section-wrap">
          <p className="eyebrow" data-reveal>— 06 / SURFACE</p><h2 data-reveal>One interface. A local project graph.</h2>
          <div className="capability-grid">{capabilities.map(({ icon: Icon, command, title, body }, index) => <article key={command} className="capability-card" data-reveal style={{ "--reveal-index": index } as React.CSSProperties}><Icon aria-hidden="true" /><code>{command}</code><h3>{title}</h3><p>{body}</p></article>)}</div>
        </section>

        <section className="limits-section section-band">
          <div className="section-wrap"><p className="eyebrow" data-reveal>— 07 / LIMITS</p><h2 data-reveal>What it does not do.</h2><p className="limits-intro" data-reveal>Stated here because a tool that hides these is worse than one that has them.</p>
            <dl className="limits-list">{limits.map(([label, description], index) => <div key={label} className={`limit-row ${label === "EMBEDDINGS" ? "limit-emphasis" : ""}`} data-reveal style={{ "--reveal-index": index } as React.CSSProperties}><dt>{label}</dt><dd>{description}</dd></div>)}</dl>
          </div>
        </section>

        <section id="docs" className="docs-section section-wrap">
          <p className="eyebrow" data-reveal>— 08 / DOCUMENTATION</p>
          <h2 data-reveal>Everything is written down.</h2>
          <p className="docs-intro" data-reveal>Including the parts that did not work. Each phase log records what broke before it shipped, each benchmark carries the command that produced it, and both decision records argue against building more.</p>
          <div className="docs-groups">
            {docGroups.map((group, groupIndex) => (
              <section key={group.heading} className="docs-group" data-reveal style={{ "--reveal-index": groupIndex } as React.CSSProperties}>
                <header className="docs-group-head"><h3>{group.heading}</h3><p>{group.note}</p></header>
                <ul className="docs-list">
                  {group.items.map(([title, path, href, body]) => (
                    <li key={path}>
                      <a href={href} target="_blank" rel="noreferrer">
                        <span className="docs-title">{title}<ArrowRight aria-hidden="true" /></span>
                        <code>{path}</code>
                        <p>{body}</p>
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
          <p className="docs-footnote" data-reveal>Read them in the repository — <a href={REPO} target="_blank" rel="noreferrer">github.com/jainrakshit24/nexus</a></p>
        </section>

        <section id="install" className="install-section section-wrap">
          <GraphCanvas className="install-graph" />
          <div className="install-content"><p className="eyebrow" data-reveal>— 08 / INSTALL</p><h2 data-reveal>Stop re-explaining your codebase.</h2><p data-reveal>One command. Runs locally. MIT.</p>
            <div className="install-cards">{(Object.keys(installCommands) as InstallTab[]).map((method, index) => <article className="install-card" data-reveal style={{ "--reveal-index": index } as React.CSSProperties} key={method}><p className="eyebrow">{method}</p><code>{installCommands[method]}</code><CopyCommand command={installCommands[method]} label={`Copy ${method} install command`} /></article>)}</div>
            <div className="install-links"><a className="text-link" href="https://github.com/jainrakshit24/nexus" target="_blank" rel="noreferrer">View on GitHub <ArrowRight aria-hidden="true" /></a><a className="text-link" href="#proof">Read the benchmarks <ArrowRight aria-hidden="true" /></a></div>
          </div>
        </section>
      </main>

      <footer className="site-footer section-wrap"><a href="#top" className="footer-brand"><ConstellationMark /><span>NEXUS</span><small>MIT · built for agents that forget</small></a><div className="footer-links"><div><p>DOCS</p><a href="https://github.com/jainrakshit24/nexus/blob/main/docs/BLUEPRINT.md" target="_blank" rel="noreferrer">Blueprint</a><a href="https://github.com/jainrakshit24/nexus/blob/main/docs/BENCHMARK.md" target="_blank" rel="noreferrer">Benchmarks</a><a href="https://github.com/jainrakshit24/nexus/blob/main/docs/COMPATIBILITY.md" target="_blank" rel="noreferrer">Compatibility</a><a href="https://github.com/jainrakshit24/nexus/tree/main/docs/adr" target="_blank" rel="noreferrer">ADRs</a></div><div><p>SOURCE</p><a href="https://github.com/jainrakshit24/nexus" target="_blank" rel="noreferrer">GitHub</a><a href="https://github.com/jainrakshit24/nexus/issues" target="_blank" rel="noreferrer">Issues</a><a href="https://github.com/jainrakshit24/nexus/blob/main/LICENSE" target="_blank" rel="noreferrer">License</a></div><div><p>INSTALL</p><a href="#install">skills.sh</a><a href="#install">Claude Code</a><a href="#install">pip</a></div></div><span id="limits" className="footer-anchor" /></footer>
    </div>
  );
}

function TerminalPanel({ step }: { step: (typeof workflowSteps)[number] }) {
  return <div className="terminal-panel" aria-label={`Terminal output for ${step.name.toLowerCase()}`}><div className="terminal-bar"><span /><span /><span /><code>nexus — project/</code></div><div className="terminal-content"><p className="terminal-command"><span>$</span> {step.command}</p><pre>{step.output.map((line, index) => <span key={`${step.name}-${index}`} className={line.includes("BREAKING") || line.includes("BLOCKED") ? "terminal-warn" : line.includes("verified") || line.includes("passed") ? "terminal-good" : ""}>{line || " "}{"\n"}</span>)}</pre><span className="terminal-cursor" aria-hidden="true" /></div></div>;
}