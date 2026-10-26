import { ApiError, definePage, html } from "simpy-ts/frontend";
import { api } from "simpy-ts/api";

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Username atau password salah.";
    if (error.status === 403) return "Sesi keamanan kedaluwarsa. Muat ulang halaman.";
    if (error.status === 409) return "Username sudah dipakai.";
    if (error.status === 422) return "Username 3-32 karakter, password 8-128 karakter.";
    if (error.status === 429) return "Terlalu banyak percobaan. Coba lagi nanti.";
  }
  return "Terjadi kesalahan.";
}

export default definePage({
  render: () => html`
    <main>
      <h1>Akun</h1>
      <p id="status" aria-live="polite">Memeriksa sesi...</p>
      <form id="auth-form" hidden>
        <input name="username" placeholder="Username" minlength="3" maxlength="32" required
          autocomplete="username">
        <input name="password" type="password" placeholder="Password (min. 8)" minlength="8"
          maxlength="128" required autocomplete="current-password">
        <button type="submit">Masuk</button>
        <button type="button" id="register">Daftar</button>
      </form>
      <button id="sign-out" type="button" hidden>Keluar</button>
      <p><a href="/">Beranda</a></p>
    </main>
  `,
  mount(root) {
    const status = root.querySelector("#status");
    const form = root.querySelector<HTMLFormElement>("#auth-form");
    const register = root.querySelector("#register");
    const signOut = root.querySelector<HTMLButtonElement>("#sign-out");
    if (!status || !form || !register || !signOut) {
      return;
    }
    const show = (username: string | null) => {
      form.hidden = username !== null;
      signOut.hidden = username === null;
      status.textContent = username === null ? "Belum masuk." : `Masuk sebagai ${username}.`;
    };
    const credentials = () => {
      const data = new FormData(form);
      return {
        username: String(data.get("username") ?? ""),
        password: String(data.get("password") ?? ""),
      };
    };

    api.me().then((user) => show(user.username), () => show(null));

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        show((await api.signIn(credentials())).username);
        form.reset();
      } catch (error) {
        status.textContent = describe(error);
      }
    });
    register.addEventListener("click", async () => {
      if (!form.reportValidity()) return;
      try {
        show((await api.register(credentials())).username);
        form.reset();
      } catch (error) {
        status.textContent = describe(error);
      }
    });
    signOut.addEventListener("click", async () => {
      try {
        await api.signOut();
        show(null);
      } catch (error) {
        status.textContent = describe(error);
      }
    });
  },
});
