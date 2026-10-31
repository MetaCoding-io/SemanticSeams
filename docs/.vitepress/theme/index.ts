/**
 * The default theme plus two things. First, a button at the left edge that folds the sidebar
 * away and gives the page its width (remembered per browser). The same control the
 * regulator docs use; nothing else about the default theme changes. The button renders
 * only where a sidebar exists and only at widths where the sidebar is shown. Second,
 * Mermaid: config.ts turns a mermaid fence (or a snippet import of a derived .mmd) into
 * a <pre class="mermaid">, and the browser renders it after each page load. Mermaid comes
 * from the CDN, once, so the docs carry no npm dependency for it.
 */
import DefaultTheme from "vitepress/theme";
import { useSidebar } from "vitepress/theme";
import { useRoute } from "vitepress";
import { defineComponent, h, nextTick, onMounted, ref, watch } from "vue";
import "./custom.css";

const STORAGE_KEY = "semanticseams-docs:sidebar-hidden";

const SidebarToggle = defineComponent({
  name: "SidebarToggle",
  setup() {
    const { hasSidebar } = useSidebar();
    const hidden = ref(false);
    function apply(value: boolean): void {
      hidden.value = value;
      document.documentElement.classList.toggle("sidebar-hidden", value);
      try { localStorage.setItem(STORAGE_KEY, value ? "1" : "0"); } catch { /* private window, blocked storage */ }
    }
    onMounted(() => {
      let stored = false;
      try { stored = localStorage.getItem(STORAGE_KEY) === "1"; } catch { /* as above */ }
      apply(stored);
    });
    return () => hasSidebar.value
      ? h("button", {
          type: "button",
          class: ["sidebar-toggle", { "is-hidden": hidden.value }],
          "aria-label": hidden.value ? "Show the sidebar" : "Hide the sidebar",
          title: hidden.value ? "Show the sidebar" : "Hide the sidebar",
          onClick: () => apply(!hidden.value),
        }, hidden.value ? "›" : "‹")
      : null;
  },
});

const MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
type Mermaid = { initialize(config: object): void; run(options: { nodes: Element[] }): Promise<void> };
let mermaid: Promise<Mermaid> | null = null;

async function renderMermaid(): Promise<void> {
  const nodes = Array.from(document.querySelectorAll("pre.mermaid:not([data-processed])"));
  if (!nodes.length) return;
  try {
    mermaid ??= import(/* @vite-ignore */ MERMAID).then((module) => module.default as Mermaid);
    const m = await mermaid;
    const dark = document.documentElement.classList.contains("dark");
    m.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default" });
    await m.run({ nodes });
  } catch (error) {
    mermaid = null; // a failed CDN load is retried on the next page
    console.error("mermaid render failed", error);
  }
}

/** Renders nothing; runs Mermaid once mounted and again after every route change. */
const MermaidRenderer = defineComponent({
  name: "MermaidRenderer",
  setup() {
    const route = useRoute();
    onMounted(renderMermaid);
    watch(() => route.path, () => nextTick(renderMermaid));
    return () => null;
  },
});

export default {
  extends: DefaultTheme,
  Layout: () => h(DefaultTheme.Layout, null, {
    "layout-bottom": () => [h(SidebarToggle), h(MermaidRenderer)],
  }),
};
