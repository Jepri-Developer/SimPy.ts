import { ApiError, definePage, html } from "simpy-ts/frontend";
import { api } from "simpy-ts/api";

export default definePage({
  render: () => html`
    <main>
      <h1>Hello from hello-world</h1>
      <form>
        <input name="name" placeholder="Nama kamu" maxlength="50" required>
        <button type="submit">Sapa</button>
      </form>
      <p id="result" aria-live="polite"></p>
      <p><a href="/about?name=Ani">About</a> | <a href="/account">Akun</a></p>
    </main>
  `,
  mount(root) {
    const form = root.querySelector("form");
    const input = root.querySelector("input");
    const result = root.querySelector("#result");
    if (!form || !input || !result) {
      return;
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      result.textContent = "Memuat...";
      try {
        const reply = await api.greet({ name: input.value });
        result.textContent = reply.message; // textContent: aman dari XSS
      } catch (error) {
        result.textContent =
          error instanceof ApiError && error.status === 422
            ? "Nama harus 1-50 karakter."
            : "Terjadi kesalahan. Coba lagi.";
      }
    });
  },
});
