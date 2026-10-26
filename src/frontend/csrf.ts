/** Token CSRF dibaca dari cookie yang dipasang server (bukan HttpOnly, sengaja bisa dibaca JS). */

const COOKIE_NAMES = ["__Host-simpy_csrf", "simpy_csrf"];

/** Cari token CSRF di string cookie (format document.cookie). */
export function readCsrfToken(cookieString: string): string | null {
  const jar = new Map<string, string>();
  for (const part of cookieString.split(";")) {
    const index = part.indexOf("=");
    if (index > 0) {
      const name = part.slice(0, index).trim();
      if (!jar.has(name)) {
        jar.set(name, part.slice(index + 1).trim());
      }
    }
  }
  for (const name of COOKIE_NAMES) {
    const value = jar.get(name);
    if (value) {
      return value;
    }
  }
  return null;
}

/** Token CSRF saat ini dari document.cookie, atau null (mis. di luar browser). */
export function currentCsrfToken(): string | null {
  return typeof document === "undefined" ? null : readCsrfToken(document.cookie);
}
