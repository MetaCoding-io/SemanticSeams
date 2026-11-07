import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitepress";

/**
 * The course site is the `course/` directory rendered as-is. It is published inside the
 * project page's GitHub Pages site, under /course/, beside the docs under /docs/. Set
 * COURSE_BASE to move it, and DOCS_SITE if the docs move to another address.
 *
 * Lessons link into the repository with ordinary relative links, the way the docs do,
 * so the same Markdown reads on GitHub and on the site. At build time a relative link
 * that leaves `course/` is rewritten: a page the docs site builds becomes a link to that
 * page on the docs site; anything else (an example model, an ontology file, a research
 * note) becomes a link into the repository on GitHub. A link to a file that does not
 * exist fails the build, which is the cross-site dead-link check.
 */
const COURSE = fileURLToPath(new URL("..", import.meta.url));
const ROOT = path.resolve(COURSE, "..");
const DOCS = path.join(ROOT, "docs");
const REPO = "https://github.com/MetaCoding-io/SemanticSeams";
const PROJECT_PAGE = "https://metacoding-io.github.io/SemanticSeams/";
const BASE = process.env.COURSE_BASE ?? "/SemanticSeams/course/";
const DOCS_SITE = process.env.DOCS_SITE ?? `${PROJECT_PAGE}docs/`;
/** Directories under `docs/` the docs site does not build; a link into one goes to GitHub. */
const DOCS_OFF_SITE = ["research", "queries", "generation", "scripts", "public", ".vitepress"];

/** The address of a docs page on the docs site, or undefined if the docs site does not build it. */
function docsPage(absolute: string): string | undefined {
  if (!absolute.startsWith(DOCS + path.sep)) return undefined;
  const relative = path.relative(DOCS, absolute).split(path.sep).join("/");
  if (DOCS_OFF_SITE.some((dir) => relative === dir || relative.startsWith(`${dir}/`))) return undefined;
  if (relative === "README.md" || !relative.endsWith(".md")) return undefined;
  // generated reference pages are rewritten by the docs site; the sources are not pages
  const page = relative.replace(/(^|\/)index\.md$/, "$1").replace(/\.md$/, "");
  return `${DOCS_SITE}${page}`;
}

const modules = [
  {
    text: "A · Where the ideas came from",
    items: [
      ["1 · Drawing software", "01-drawing-software"],
      ["2 · Saying what, not how", "02-saying-what-not-how"],
      ["3 · The program that writes the program", "03-the-program-that-writes-the-program"],
      ["4 · Why it kept stalling", "04-why-it-kept-stalling"],
    ],
  },
  {
    text: "B · One graph, every diagram a view",
    items: [
      ["5 · One graph, many views", "05-one-graph-many-views"],
      ["6 · Shapes before generation", "06-shapes-before-generation"],
      ["7 · Interpret behaviour, generate structure", "07-interpret-behaviour-generate-structure"],
      ["8 · Questions no single tool can answer", "08-questions-no-single-tool-can-answer"],
    ],
  },
  {
    text: "C · The hard problems, addressed",
    items: [
      ["9 · Code the templates cannot write", "09-code-the-templates-cannot-write"],
      ["10 · Getting changes back into the model", "10-getting-changes-back-into-the-model"],
      ["11 · Same model, same bytes", "11-same-model-same-bytes"],
    ],
  },
  {
    text: "D · The frontier",
    items: [
      ["12 · What is still open", "12-what-is-still-open"],
    ],
  },
] as const;

export default defineConfig({
  title: "SemanticSeams Course",
  description: "From diagrams to running systems: a course on model-based engineering, code generation, what went wrong, and what SemanticSeams does about it.",
  base: BASE,
  lang: "en-US",
  lastUpdated: true,
  cleanUrls: true,
  // Every internal link must resolve; only http://localhost links (the viewer, run locally) are exempt.
  ignoreDeadLinks: "localhostLinks",
  srcExclude: ["README.md", "diagrams/README.md", "node_modules/**"],
  head: [
    ["link", { rel: "icon", type: "image/svg+xml", href: `${BASE}favicon.svg` }],
    ["link", { rel: "preconnect", href: "https://fonts.googleapis.com" }],
    ["link", { rel: "preconnect", href: "https://fonts.gstatic.com", crossorigin: "" }],
    ["link", { rel: "stylesheet", href: "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap" }],
  ],
  themeConfig: {
    logo: "/favicon.svg",
    siteTitle: "SemanticSeams Course",
    nav: [
      { text: "Lessons", link: "/lessons/01-drawing-software" },
      { text: "Scorecard", link: "/scorecard" },
      { text: "Capstone", link: "/capstone" },
      { text: "Instructors", link: "/instructor" },
      { text: "Docs", link: DOCS_SITE },
      { text: "Project page", link: PROJECT_PAGE },
    ],
    sidebar: [
      {
        text: "The course",
        collapsed: false,
        items: [
          { text: "Overview and syllabus", link: "/" },
          { text: "The scorecard", link: "/scorecard" },
          { text: "Before the first lesson", link: "/setup" },
        ],
      },
      ...modules.map((module) => ({
        text: module.text,
        collapsed: false,
        items: module.items.map(([text, slug]) => ({ text, link: `/lessons/${slug}` })),
      })),
      {
        text: "After the lessons",
        collapsed: false,
        items: [
          { text: "Capstone", link: "/capstone" },
          { text: "Reading list", link: "/reading" },
          { text: "For instructors", link: "/instructor" },
        ],
      },
    ],
    socialLinks: [{ icon: "github", link: REPO }],
    editLink: {
      pattern: `${REPO}/edit/main/course/:path`,
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
          if (!absolute.startsWith(COURSE)) {
            if (!fs.existsSync(absolute)) {
              throw new Error(`${path.relative(ROOT, file)} links to ${href}, which does not exist in the repository`);
            }
            const suffix = hash ? `#${hash}` : "";
            const page = docsPage(absolute);
            if (page) {
              token.attrSet("href", `${page}${suffix}`);
            } else {
              const relative = path.relative(ROOT, absolute).split(path.sep).join("/");
              const kind = fs.statSync(absolute).isDirectory() ? "tree" : "blob";
              token.attrSet("href", `${REPO}/${kind}/main/${relative}${suffix}`);
            }
          }
        }
        return fallback(tokens, idx, options, env, self);
      };
      // A ```mermaid fence becomes a <pre class="mermaid"> the theme renders in the browser.
      const fence = md.renderer.rules.fence!;
      md.renderer.rules.fence = (tokens, idx, options, env, self) => {
        const token = tokens[idx]!;
        if (/^mermaid(?![\w-])/.exec(token.info.trim()) === null) return fence(tokens, idx, options, env, self);
        return `<pre class="mermaid" v-pre>${md.utils.escapeHtml(token.content)}</pre>\n`;
      };
    },
  },
});
