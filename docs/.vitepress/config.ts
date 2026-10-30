import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitepress";

/**
 * The site is the `docs/` directory rendered as-is, plus what `scripts/generate.py`
 * writes into `docs/generated/` from the model's own sources (the seam ontology, the
 * layer vocabularies, the SHACL shapes and the query catalog). Generated pages are
 * rewritten to `reference/`. `docs/research/` (design notes on what comes next),
 * `docs/generation/` (golden fixtures for the generator tests) and `docs/queries/`
 * (the raw catalog, rendered as /reference/queries) are not built.
 *
 * A relative link that leaves `docs/`, or points into a directory the site does not
 * build, becomes a link into the repository on GitHub, so the same Markdown reads on
 * GitHub and on the site without two copies of every link.
 *
 * The site is published inside the project page's GitHub Pages site, under /docs/.
 * Set DOCS_BASE to move it, for example to "/" on a custom docs domain.
 */
const DOCS = fileURLToPath(new URL("..", import.meta.url));
const ROOT = path.resolve(DOCS, "..");
const REPO = "https://github.com/MetaCoding-io/SemanticSeams";
const PROJECT_PAGE = "https://metacoding-io.github.io/SemanticSeams/";
const BASE = process.env.DOCS_BASE ?? "/SemanticSeams/docs/";
/** Directories under `docs/` the site does not build; a link into one goes to GitHub. */
const OFF_SITE = ["research", "queries", "generation"];

const decisions = [
  ["0001", "Named-graph partitioning", "0001-named-graph-partitioning"],
  ["0002", "IRI identity and migration", "0002-iri-identity-and-migration"],
  ["0003", "Payload resolution", "0003-payload-resolution"],
  ["0004", "View response contract", "0004-view-response-contract"],
  ["0005", "Navigation resolution", "0005-navigation-resolution"],
  ["0006", "Index-payload drift lint", "0006-index-payload-drift-lint"],
  ["0007", "Execution strategy", "0007-execution-strategy"],
  ["0008", "Node-link renderer", "0008-node-link-renderer"],
  ["0009", "Human tasks", "0009-human-tasks"],
  ["0010", "Channel-started processes", "0010-channel-started-processes"],
  ["0011", "Storage resolution", "0011-storage-resolution"],
] as const;

export default defineConfig({
  title: "SemanticSeams",
  description: "A zoomable, multi-notation application graph. One RDF graph is the source of truth; diagrams are views.",
  base: BASE,
  lang: "en-US",
  lastUpdated: true,
  cleanUrls: true,
  // Every internal link must resolve; only http://localhost links (the viewer, run locally) are exempt.
  ignoreDeadLinks: "localhostLinks",
  srcExclude: [...OFF_SITE.map((dir) => `${dir}/**`), "README.md", "scripts/**", "node_modules/**"],
  rewrites: {
    "generated/seam-predicates.md": "reference/seam-predicates.md",
    "generated/vocabularies.md": "reference/vocabularies.md",
    "generated/shapes.md": "reference/shapes.md",
    "generated/queries.md": "reference/queries.md",
  },
  head: [
    ["link", { rel: "icon", type: "image/svg+xml", href: `${BASE}favicon.svg` }],
    ["link", { rel: "preconnect", href: "https://fonts.googleapis.com" }],
    ["link", { rel: "preconnect", href: "https://fonts.gstatic.com", crossorigin: "" }],
    ["link", { rel: "stylesheet", href: "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" }],
  ],
  themeConfig: {
    logo: "/favicon.svg",
    siteTitle: "SemanticSeams",
    nav: [
      { text: "Guide", link: "/guide/getting-started" },
      { text: "Tutorials", link: "/tutorials/expenses/" },
      { text: "Concepts", link: "/concepts/diagrams-are-views" },
      { text: "Reference", link: "/reference/seam-predicates" },
      { text: "Project", link: "/project-outline" },
      { text: "Project page", link: PROJECT_PAGE },
      { text: "MetaCoding", link: "https://metacoding.io" },
    ],
    sidebar: [
      {
        text: "Guide",
        collapsed: false,
        items: [
          { text: "Getting started", link: "/guide/getting-started" },
          { text: "Using the viewer", link: "/guide/the-viewer" },
          { text: "Authoring a model", link: "/guide/authoring-a-model" },
          { text: "Write your own generator", link: "/guide/write-your-own-generator" },
        ],
      },
      {
        text: "Tutorials",
        collapsed: false,
        items: [
          { text: "Quick start: the chat app", link: "/tutorial" },
          {
            text: "Build an expense approval app",
            link: "/tutorials/expenses/",
            collapsed: false,
            items: [
              { text: "1 · The architecture", link: "/tutorials/expenses/01-architecture" },
              { text: "2 · The data", link: "/tutorials/expenses/02-data" },
              { text: "3 · The screens", link: "/tutorials/expenses/03-screens" },
              { text: "4 · The process", link: "/tutorials/expenses/04-process" },
              { text: "5 · The rules", link: "/tutorials/expenses/05-rules" },
              { text: "6 · The lifecycle", link: "/tutorials/expenses/06-lifecycle" },
              { text: "7 · People and permissions", link: "/tutorials/expenses/07-permissions" },
              { text: "8 · Growing up", link: "/tutorials/expenses/08-growing-up" },
            ],
          },
        ],
      },
      {
        text: "Concepts",
        collapsed: false,
        items: [
          { text: "Diagrams are views", link: "/concepts/diagrams-are-views" },
          { text: "The seams", link: "/concepts/the-seams" },
          { text: "Cross-layer queries", link: "/concepts/cross-layer-queries" },
        ],
      },
      {
        text: "Reference",
        collapsed: false,
        items: [
          { text: "seams library (Python API)", link: "/reference/seams-library" },
          { text: "Seam predicates", link: "/reference/seam-predicates" },
          { text: "Layer vocabularies", link: "/reference/vocabularies" },
          { text: "SHACL shapes", link: "/reference/shapes" },
          { text: "Query catalog", link: "/reference/queries" },
          { text: "View response contract", link: "/adr/0004-view-response-contract" },
        ],
      },
      {
        text: "Project",
        collapsed: false,
        items: [
          { text: "Project outline", link: "/project-outline" },
          { text: "Backlog", link: "/backlog" },
          {
            text: "Decisions",
            link: "/adr/",
            collapsed: true,
            items: decisions.map(([n, title, slug]) => ({ text: `${n} · ${title}`, link: `/adr/${slug}` })),
          },
          { text: "Status", link: `${PROJECT_PAGE}#status` },
          { text: "Publishing the site", link: "/project/publishing" },
        ],
      },
    ],
    socialLinks: [{ icon: "github", link: REPO }],
    editLink: {
      pattern: `${REPO}/edit/main/docs/:path`,
      text: "Edit this page on GitHub",
    },
    search: { provider: "local" },
    footer: {
      message: "Released under the Apache-2.0 License.",
      copyright: 'Copyright © 2026–present <a href="https://metacoding.io">MetaCoding</a> · a MetaCoding project',
    },
    outline: { level: [2, 3] },
  },
  markdown: {
    // Shiki has no TriG grammar; TriG is Turtle plus named-graph blocks, so Turtle highlights it.
    languageAlias: { trig: "turtle" },
    config(md) {
      const fallback = md.renderer.rules.link_open ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));
      md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
        const token = tokens[idx]!;
        const href = token.attrGet("href");
        const file: string | undefined = env?.path;
        if (href && file && !/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(href)) {
          const [target, hash] = href.split("#");
          const absolute = path.resolve(path.dirname(file), target!);
          if (!absolute.startsWith(DOCS) || OFF_SITE.some((dir) => absolute.startsWith(path.join(DOCS, dir)))) {
            const relative = path.relative(ROOT, absolute).split(path.sep).join("/");
            const kind = /\.[a-z0-9]+$/i.test(relative) ? "blob" : "tree";
            token.attrSet("href", `${REPO}/${kind}/main/${relative}${hash ? `#${hash}` : ""}`);
          }
        }
        return fallback(tokens, idx, options, env, self);
      };
    },
  },
});
