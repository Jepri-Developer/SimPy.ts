import pytest
from asgi_helper import Client, call

from simpy import (
    HTTPError,
    Schema,
    Session,
    SimPy,
    UserExists,
    hash_password,
    login,
    logout,
    verify_password,
)
from simpy.auth import Database, SessionStore, UserStore
from simpy.config import Settings


def dev_settings():
    return Settings(env="test", secret_key="k" * 40, session_db=":memory:")


def prod_settings():
    return Settings(env="production", secret_key="k" * 40, session_db=":memory:")


# --- hash password ------------------------------------------------------------------------------


def test_hash_format_and_verification():
    stored = hash_password("kata-sandi-rahasia")
    assert stored.startswith("scrypt$16384$8$1$")
    assert "kata-sandi-rahasia" not in stored
    assert verify_password("kata-sandi-rahasia", stored)
    assert not verify_password("kata-sandi-salah", stored)
    assert not verify_password("", stored)


def test_hashes_use_random_salt():
    assert hash_password("sama") != hash_password("sama")


def test_unicode_is_normalized():
    composed, decomposed = "caf\u00e9-sandi", "cafe\u0301-sandi"
    assert verify_password(decomposed, hash_password(composed))


def test_password_length_limits():
    with pytest.raises(ValueError):
        hash_password("")
    with pytest.raises(ValueError):
        hash_password("x" * 1025)
    assert verify_password("x" * 1025, hash_password("x")) is False


@pytest.mark.parametrize(
    "stored",
    ["", "bukan-hash", "bcrypt$1$2$3$a$b", "scrypt$16384$8$1$salt", "scrypt$abc$8$1$AAAA$AAAA",
     "scrypt$3$8$1$AAAA$AAAA", "scrypt$1073741824$8$1$AAAA$AAAA", "scrypt$16384$8$1$!!$!!"],
)
def test_malformed_hashes_never_raise(stored):
    assert verify_password("apa-saja", stored) is False


# --- pengguna & sesi ------------------------------------------------------------------------------


def test_user_store():
    users = UserStore(Database(":memory:"))
    user = users.create("Ani", "sandi-panjang-1")
    assert user.username == "Ani" and user.id.isdigit()
    with pytest.raises(UserExists):
        users.create("ani", "sandi-panjang-2")  # tidak peka huruf besar/kecil
    assert users.authenticate("ANI", "sandi-panjang-1").id == user.id
    assert users.authenticate("ani", "salah-salah") is None
    assert users.authenticate("tidak-ada", "sandi-panjang-1") is None
    assert users.get(user.id).username == "Ani"
    assert users.get("999") is None and users.get("abc") is None and users.get("1; DROP") is None


def test_sql_injection_attempts_are_inert():
    users = UserStore(Database(":memory:"))
    users.create("ani", "sandi-panjang-1")
    assert users.authenticate("' OR '1'='1", "x") is None
    assert users.authenticate("ani' --", "sandi-panjang-1") is None


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def make_store(**kwargs):
    clock = Clock()
    db = Database(":memory:")
    return SessionStore(db, clock=clock, **kwargs), clock, db


def test_session_create_and_get():
    store, _clock, db = make_store()
    raw, session = store.create("42")
    assert store.get(raw) == session and session.user_id == "42"
    stored_ids = [row[0] for row in db.query("SELECT id_hash FROM sessions")]
    assert stored_ids and raw not in stored_ids  # hanya hash yang disimpan


def test_session_ids_are_unique_and_long():
    store, _clock, _db = make_store()
    ids = {store.create("1")[0] for _ in range(50)}
    assert len(ids) == 50 and all(len(i) >= 40 for i in ids)


def test_invalid_session_ids_are_rejected():
    store, _clock, _db = make_store()
    for bad in (None, "", "pendek", "a" * 101, "x'; DROP TABLE sessions;--" + "a" * 20, "tidak-ada-" + "a" * 30):
        assert store.get(bad) is None


def test_absolute_expiry_and_idle_timeout():
    store, clock, _db = make_store(lifetime=1000, idle_timeout=300)
    raw, _ = store.create("1")
    clock.now += 200
    assert store.get(raw) is not None  # menyegarkan last_seen
    clock.now += 250
    assert store.get(raw) is not None  # masih dalam idle timeout sejak akses terakhir
    clock.now += 350
    assert store.get(raw) is None  # idle terlalu lama
    raw2, _ = store.create("1")
    for _ in range(3):
        clock.now += 250
        assert store.get(raw2) is not None
    clock.now += 250
    assert store.get(raw2) is None  # mencapai masa hidup absolut (1000 detik)


def test_delete_and_delete_user_and_purge():
    store, clock, db = make_store(lifetime=100)
    a, _ = store.create("1")
    b, _ = store.create("1")
    c, _ = store.create("2")
    store.delete(a)
    assert store.get(a) is None and store.get(b) is not None
    assert store.delete_user("1") == 1
    assert store.get(b) is None and store.get(c) is not None
    clock.now += 500
    assert store.purge_expired() == 1
    assert db.query("SELECT COUNT(*) FROM sessions") == [(0,)]


def test_file_database_gets_private_permissions(tmp_path):
    path = tmp_path / "data" / "s.db"
    Database(str(path)).close()
    assert path.exists()
    assert (path.stat().st_mode & 0o077) == 0


# --- integrasi dengan aplikasi ----------------------------------------------------------------------


class Body(Schema):
    note: str


def make_app(settings=None):
    app = SimPy(settings=settings or dev_settings())

    @app.post("/sign-in")
    def sign_in(request):
        login(request, "42")
        return {"ok": True}

    @app.post("/sign-out")
    def sign_out(request):
        logout(request)

    @app.get("/me", auth=True)
    def me(session: Session):
        return {"user": session.user_id}

    @app.get("/who")
    def who(session: Session | None):
        return {"anonymous": session is None}

    @app.post("/secret", auth=True)
    def secret(data: Body):
        return {"note": data.note}

    return app


def test_auth_required_routes_reject_anonymous():
    resp = call(make_app(), "GET", "/me")
    assert resp.status == 401 and resp.json()["error"] == "unauthorized"


def test_login_sets_cookies_and_grants_access():
    client = Client(make_app())
    resp = client.post("/sign-in", json=None)
    assert resp.status == 200
    session_cookie = resp.cookie("simpy_session")
    assert "HttpOnly" in session_cookie and "SameSite=Lax" in session_cookie
    assert "Path=/" in session_cookie and "Secure" not in session_cookie
    assert resp.cookie("simpy_csrf") is not None
    assert client.get("/me").json() == {"user": "42"}
    assert client.get("/who").json() == {"anonymous": False}
    assert call(make_app(), "GET", "/who").json() == {"anonymous": True}


def test_session_cookie_is_not_the_stored_value():
    app = make_app()
    client = Client(app)
    client.post("/sign-in")
    raw = client.cookies["simpy_session"]
    assert all(raw not in str(row) for row in app.database.query("SELECT * FROM sessions"))


def test_logout_revokes_session_on_the_server():
    app = make_app()
    client = Client(app)
    client.post("/sign-in")
    stolen = dict(client.cookies)
    assert client.post("/sign-out").status == 204
    assert client.get("/me").status == 401
    attacker = Client(app)
    attacker.cookies.update(stolen)  # cookie lama diputar ulang
    assert attacker.get("/me").status == 401


def test_login_replaces_previous_session():
    app = make_app()
    client = Client(app)
    client.post("/sign-in")
    first = client.cookies["simpy_session"]
    client.post("/sign-in")
    assert client.cookies["simpy_session"] != first
    old = Client(app)
    old.cookies["simpy_session"] = first
    assert old.get("/me").status == 401  # anti session fixation


def test_csrf_token_rotates_on_login_and_logout():
    app = make_app()
    client = Client(app)
    client.get("/who")
    anonymous_token = client.csrf_token()
    client.post("/sign-in")
    logged_in_token = client.csrf_token()
    assert logged_in_token != anonymous_token
    # token milik sebelum login tidak boleh berlaku untuk sesi baru
    stale = Client(app, auto_csrf=False)
    stale.cookies.update(client.cookies)
    stale.cookies["simpy_csrf"] = anonymous_token
    resp = stale.post("/secret", json={"note": "x"}, headers={"x-csrf-token": anonymous_token})
    assert resp.status == 403 and resp.json()["error"] == "csrf_failed"
    client.post("/sign-out")
    assert client.csrf_token() not in (anonymous_token, logged_in_token)
    assert client.post("/who", json={}).status in (200, 405)  # token baru berlaku


def test_garbage_session_cookie_means_anonymous():
    app = make_app()
    for value in ("x", "a" * 43, "'; DROP TABLE sessions;--", "%00"):
        client = Client(app)
        client.cookies["simpy_session"] = value
        assert client.get("/me").status == 401, value


def test_auth_route_with_body_checks_auth_after_csrf():
    app = make_app()
    client = Client(app)
    assert client.post("/secret", json={"note": "a"}).status == 401
    client.post("/sign-in")
    assert client.post("/secret", json={"note": "a"}).json() == {"note": "a"}


def test_production_cookies_are_secure_and_prefixed():
    client = Client(make_app(prod_settings()))
    resp = client.post("/sign-in")
    cookie = resp.cookie("__Host-simpy_session")
    assert cookie is not None and "Secure" in cookie and "HttpOnly" in cookie
    assert "Domain" not in cookie
    assert client.get("/me").json() == {"user": "42"}


def test_database_is_created_lazily():
    app = make_app()
    assert app._database is None
    call(app, "GET", "/who")
    assert app._database is None  # tanpa cookie sesi, tidak menyentuh DB
    Client(app).post("/sign-in")
    assert app._database is not None


def test_misconfiguration_fails_early():
    app = SimPy()
    with pytest.raises(ValueError):

        @app.get("/x", auth=True)
        def x(session: Session):
            return {}

    with pytest.raises(ValueError):

        @app.get("/y")
        def y(session):
            return {}

    with pytest.raises(RuntimeError):
        app.database

    class Fake:
        scope: dict = {}
        headers: dict = {}

    with pytest.raises(RuntimeError):
        login(Fake(), "1")
    with pytest.raises(RuntimeError):
        logout(Fake())


def test_http_error_still_works_with_auth_routes():
    app = SimPy(settings=dev_settings())

    @app.get("/boom", auth=True)
    def boom(session: Session):
        raise HTTPError(418, "teko")

    client = Client(app)
    assert client.get("/boom").status == 401
