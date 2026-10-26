/**
 * Template HTML aman: nilai yang disisipkan di-escape otomatis (proteksi XSS by design).
 * Hanya `SafeHtml` yang boleh masuk ke innerHTML; string biasa tidak pernah dipercaya.
 */

/** HTML yang sudah aman (hasil `html` atau `raw`). */
export class SafeHtml {
  readonly value: string;

  constructor(value: string) {
    this.value = value;
  }

  toString(): string {
    return this.value;
  }
}

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
  "`": "&#96;",
};

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"'`]/g, (char) => ESCAPES[char] ?? char);
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === false || value === true) {
    return "";
  }
  if (value instanceof SafeHtml) {
    return value.value;
  }
  if (Array.isArray(value)) {
    return value.map(renderValue).join("");
  }
  return escapeHtml(String(value));
}

/**
 * Tag template: html`<p>${userInput}</p>`.
 * Selalu beri tanda kutip pada atribut (title="${x}"); jangan menyisipkan nilai ke
 * konteks <script>/<style>, dan bungkus URL dengan `safeUrl()`.
 */
export function html(strings: TemplateStringsArray, ...values: unknown[]): SafeHtml {
  let output = strings[0] ?? "";
  for (let i = 0; i < values.length; i++) {
    output += renderValue(values[i]) + (strings[i + 1] ?? "");
  }
  return new SafeHtml(output);
}

/** Tandai string sebagai HTML tepercaya. HANYA untuk konten yang kamu tulis sendiri. */
export function raw(trusted: string): SafeHtml {
  return new SafeHtml(trusted);
}

const ALLOWED_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

/** Kembalikan `url` jika skemanya http/https/mailto atau relatif; selain itu "#". */
export function safeUrl(url: string): string {
  const trimmed = url.trim();
  try {
    const parsed = new URL(trimmed, "http://relative.invalid");
    return ALLOWED_PROTOCOLS.has(parsed.protocol) ? trimmed : "#";
  } catch {
    return "#";
  }
}
