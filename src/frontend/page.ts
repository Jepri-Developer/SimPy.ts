import type { SafeHtml } from "./html.ts";
import type { Mount, Page, PageContext } from "./types.ts";

export interface PageDefinition {
  render: (context: PageContext) => SafeHtml | Promise<SafeHtml>;
  mount?: Mount;
}

/** Halaman interaktif: `render` menghasilkan HTML, `mount` memasang event listener. */
export function definePage(definition: PageDefinition): Page {
  const page: Page = (context) => definition.render(context);
  if (definition.mount) {
    page.mount = definition.mount;
  }
  return page;
}
