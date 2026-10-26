import type { RouteDef } from "./types.ts";

export interface RouteMatch {
  readonly route: RouteDef;
  readonly params: Record<string, string>;
}

export function normalizePath(pathname: string): string {
  if (pathname.length > 1 && pathname.endsWith("/")) {
    return pathname.replace(/\/+$/, "") || "/";
  }
  return pathname;
}

function splitPath(path: string): string[] | null {
  if (path === "/") {
    return [];
  }
  if (!path.startsWith("/")) {
    return null;
  }
  const segments = path.slice(1).split("/");
  return segments.some((segment) => segment === "") ? null : segments;
}

/** Cari route pertama yang cocok. Urutan `routes` menentukan prioritas. */
export function matchRoute(routes: readonly RouteDef[], pathname: string): RouteMatch | null {
  const target = splitPath(normalizePath(pathname));
  if (target === null) {
    return null;
  }
  for (const route of routes) {
    const pattern = splitPath(route.pattern);
    if (pattern === null || pattern.length !== target.length) {
      continue;
    }
    const entries: [string, string][] = [];
    let matched = true;
    for (let i = 0; i < pattern.length; i++) {
      const expected = pattern[i] as string;
      const actual = target[i] as string;
      if (expected.startsWith(":")) {
        try {
          entries.push([expected.slice(1), decodeURIComponent(actual)]);
        } catch {
          matched = false; // %-encoding rusak
          break;
        }
      } else if (expected !== actual) {
        matched = false;
        break;
      }
    }
    if (matched) {
      // fromEntries membuat properti biasa (aman untuk nama seperti "__proto__").
      return { route, params: Object.fromEntries(entries) };
    }
  }
  return null;
}
