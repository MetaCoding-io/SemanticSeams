/**
 * <Diagram name="descent" caption="..." />: a course diagram, inlined as SVG so it uses the
 * page's fonts and switches with the site's dark mode. Each diagram is a light and dark
 * pair in course/diagrams/, `<name>.svg` and `<name>-dark.svg`, exported from the
 * diagram-design sources in course/diagrams/src by course/diagrams/export.sh. A missing
 * file fails the build, the way a dead link does.
 */
import { defineComponent, h } from "vue";

const svgs = import.meta.glob("../../diagrams/*.svg", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

export const Diagram = defineComponent({
  name: "Diagram",
  props: {
    name: { type: String, required: true },
    caption: { type: String, default: "" },
  },
  setup(props) {
    return () => {
      const light = svgs[`../../diagrams/${props.name}.svg`];
      const dark = svgs[`../../diagrams/${props.name}-dark.svg`];
      if (!light || !dark) throw new Error(`course/diagrams/${props.name}.svg and ${props.name}-dark.svg must both exist`);
      return h("figure", { class: "course-diagram" }, [
        h("div", { class: "course-diagram-light", innerHTML: light }),
        h("div", { class: "course-diagram-dark", innerHTML: dark }),
        props.caption ? h("figcaption", props.caption) : null,
      ]);
    };
  },
});
