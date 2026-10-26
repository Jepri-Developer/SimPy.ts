import { SafeHtml, html } from "./html.ts";
import { matchRoute } from "./router.ts";
import type { Mount, Page, PageContext, RouteDef } from "./types.ts";

export interface AppOptions {
  readonly routes: readonly RouteDef[];
  readonly notFound?: Page;
  /** Selector elemen tempat halaman dirender. Default "#app". */
  readonly root?: string;
}

export interface App {
  /** Render halaman untuk URL saat ini dan aktifkan navigasi sisi klien. */
  start(): void;
  /** Pindah halaman tanpa reload (hanya URL satu origin). */
  navigate(to: string): Promise<void>;
}

const defaultNotFound: Page = () =>
  html`<main><h1>404</h1><p>Halaman tidak ditemukan.</p></main>`;

const errorPage = html`<main><h1>Terjadi kesalahan</h1><p>Halaman tidak dapat ditampilkan.</p></main>`;

interface Resolved {
  readonly output: SafeHtml;
  readonly mount: Mount | null;
  readonly context: PageContext;
}

async function resolve(options: AppOptions, pathname: string, search: string): Promise<Resolved> {
  const match = matchRoute(options.routes, pathname);
  const context: PageContext = {
    path: pathname,
    params: match?.params ?? {},
    query: new URLSearchParams(search),
  };
  const page = match ? match.route.page : (options.notFound ?? defaultNotFound);
  try {
    const result = await page(context);
    if (!(result instanceof SafeHtml)) {
      throw new TypeError("Halaman harus mengembalikan html`...`, bukan string biasa.");
    }
    return { output: result, mount: page.mount ?? null, context };
  } catch (error) {
    // Detail error hanya ke console, tidak ke halaman.
    console.error("Halaman gagal dirender:", error);
    return { output: errorPage, mount: null, context };
  }
}

/** Hasilkan HTML untuk sebuah URL. Tidak menyentuh DOM, jadi bisa diuji di Node. */
export async function renderUrl(
  options: AppOptions,
  pathname: string,
  search = "",
): Promise<SafeHtml> {
  return (await resolve(options, pathname, search)).output;
}

export function createApp(options: AppOptions): App {
  let root: Element | null = null;
  let sequence = 0;
  let cleanup: (() => void) | null = null;

  function runCleanup(): void {
    const current = cleanup;
    cleanup = null;
    if (current) {
      try {
        current();
      } catch (error) {
        console.error("Pembersihan halaman gagal:", error);
      }
    }
  }

  async function show(): Promise<void> {
    if (root === null) {
      return;
    }
    const current = ++sequence;
    const { output, mount, context } = await resolve(options, location.pathname, location.search);
    if (current !== sequence) {
      return; // sudah ada navigasi yang lebih baru
    }
    runCleanup();
    root.innerHTML = output.value; // satu-satunya sink HTML; isinya selalu SafeHtml
    if (mount) {
      try {
        const result = mount(root, context);
        if (typeof result === "function") {
          cleanup = result;
        }
      } catch (error) {
        console.error("mount() halaman gagal:", error);
      }
    }
  }

  async function navigate(to: string): Promise<void> {
    const target = new URL(to, location.href);
    if (target.origin !== location.origin) {
      throw new Error("navigate() hanya untuk URL satu origin.");
    }
    history.pushState(null, "", target.pathname + target.search + target.hash);
    await show();
    window.scrollTo(0, 0);
  }

  function onClick(event: MouseEvent): void {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    const target = event.target as Element | null;
    const anchor = target?.closest?.("a");
    if (!anchor) {
      return;
    }
    const targetAttr = anchor.getAttribute("target");
    if ((targetAttr && targetAttr !== "_self") || anchor.hasAttribute("download")) {
      return;
    }
    let url: URL;
    try {
      url = new URL(anchor.href, location.href);
    } catch {
      return;
    }
    const isBackend = url.pathname === "/api" || url.pathname.startsWith("/api/");
    if (url.origin !== location.origin || isBackend || url.pathname.startsWith("/static/")) {
      return;
    }
    event.preventDefault();
    void navigate(url.pathname + url.search + url.hash);
  }

  function start(): void {
    const selector = options.root ?? "#app";
    const found = document.querySelector(selector);
    if (found === null) {
      throw new Error(`Elemen root '${selector}' tidak ditemukan.`);
    }
    root = found;
    window.addEventListener("popstate", () => {
      void show();
    });
    document.addEventListener("click", onClick);
    void show();
  }

  return { start, navigate };
}
