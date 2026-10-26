import { html, safeUrl, type PageContext } from "simpy-ts/frontend";

export default function render(context: PageContext) {
  const name = context.query.get("name") ?? "tamu";
  return html`
    <main>
      <h1>Tentang</h1>
      <p>Halo, ${name}! (nilai dari URL di-escape otomatis)</p>
      <a href="${safeUrl("/")}">Kembali</a>
    </main>
  `;
}
