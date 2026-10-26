import type { SafeHtml } from "./html.ts";

export interface PageContext {
  /** Path URL saat ini, mis. "/users/42". */
  readonly path: string;
  /** Parameter dinamis dari nama file, mis. pages/users/[id].ts -> { id: "42" }. */
  readonly params: Readonly<Record<string, string>>;
  readonly query: URLSearchParams;
}

/**
 * Dipanggil setelah HTML halaman masuk ke DOM; tempat memasang event listener.
 * Boleh mengembalikan fungsi pembersih, yang dipanggil sebelum halaman diganti.
 */
export type Mount = (root: Element, context: PageContext) => void | (() => void);

/** Sebuah halaman: fungsi yang mengembalikan html`...` (boleh async). */
export type Page = ((context: PageContext) => SafeHtml | Promise<SafeHtml>) & {
  mount?: Mount;
};

export interface RouteDef {
  /** Pola path: "/", "/about", "/users/:id". */
  readonly pattern: string;
  readonly page: Page;
}
