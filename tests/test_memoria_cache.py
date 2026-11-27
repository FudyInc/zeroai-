"""Egress de Supabase por la fila `app_state` (SupabaseMemory) y su caché en proceso.

Contexto: cada `make_memory()` bajaba la fila ENTERA (~108 KB, ~85 KB de `actions`) y el
dashboard abierto hace polling cada 5-30 s, así que se agotó la cuota de egress del plan
gratis (402). Estos tests fijan (1) cuánto baja una request típica de los endpoints que
el dashboard pollea y (2) que la caché no pierde escrituras ni miente cuando Supabase cae.

La frontera HTTP está simulada (`FakeSupabase` reemplaza a `sb_request`): sin red real y
sin tocar state.json / crm.json / .env.

Correr solo:  python3 -m unittest tests.test_memoria_cache -v
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from zero import memory_supabase
from zero._supabase import SupabaseError
from zero.config import MEMORY_CLOUD_CACHE_TTL_S
from zero.memory import SessionMemory

try:
    import api  # noqa: E402  (importa sin SUPABASE_*: cloud_env no sale a la red)
    _API_AVAILABLE = True
except ImportError:
    _API_AVAILABLE = False

CLIENT = "acme"
NUMERO = "56911112222"
# Lo que el dashboard abierto en la pestaña WhatsApp pollea (frontend/src, refetchInterval):
# (endpoint de api.py, cada cuántos segundos).
POLLING = (
    ("whatsapp_web_status", 15),     # WhatsAppAttentionWatcher
    ("whatsapp_web_status", 5),      # pages/Whatsapp.jsx WebStatusCard
    ("whatsapp_web_chats", 10),      # WhatsAppAttentionWatcher
    ("whatsapp_web_messages", 5),    # pages/Whatsapp.jsx / WhatsAppWebInbox
    ("whatsapp_attention", 30),      # Sidebar
    ("whatsapp_attention", 30),      # WhatsAppAttentionWatcher
    ("whatsapp_attention", 30),      # AttentionCard
    ("whatsapp_client_readiness", 30),
)


def _estado_tipico() -> dict:
    """Un estado del tamaño del real (~108 KB, la mayor parte es el log `actions`)."""
    m = SessionMemory()
    m.register_client(CLIENT, "GROWTH")
    m.set_client_agent_profile(CLIENT, {"whatsapp_number": NUMERO})
    m.actions = [{"ts": f"2026-11-27T10:{i % 60:02d}:00", "agent": "OUTREACH",
                  "action": "sent", "detail": "x" * 150} for i in range(420)]
    return m.snapshot()


def _mismo_instante(a: str, b: str) -> bool:
    return datetime.fromisoformat(a) == datetime.fromisoformat(b)


class FakeSupabase:
    """Reemplaza a `sb_request` para la fila `app_state`: cuenta lecturas y bytes."""

    def __init__(self, data: dict):
        self.row = {"data": copy.deepcopy(data), "updated": "2026-11-01T00:00:00+00:00"}
        self.down = False
        self.full_reads = self.version_reads = self.writes = self.bytes = 0

    def external_write(self, data: dict) -> None:
        """Otro proceso (script, timer) escribe la fila por su cuenta."""
        self.row = {"data": copy.deepcopy(data),
                    "updated": datetime.now(timezone.utc).isoformat()}

    def __call__(self, base_url, key, method, path, body=None, prefer=None, timeout=20):
        if self.down:
            raise SupabaseError("Supabase 402: exceed_egress_quota", code=402)
        if method == "GET":
            select = path.split("select=")[1]
            if select == "updated":
                self.version_reads += 1
                out = [{"updated": self.row["updated"]}]
            else:
                self.full_reads += 1
                out = [dict(self.row)] if select == "data,updated" else [{"data": self.row["data"]}]
            self.bytes += len(json.dumps(out))
            return out
        self.writes += 1
        fila = body[0]
        self.row = {"data": copy.deepcopy(fila["data"]),
                    "updated": fila.get("updated", self.row["updated"])}
        return None

    @property
    def reads(self) -> int:
        return self.full_reads + self.version_reads


@contextlib.contextmanager
def _nube(fake: FakeSupabase):
    memory_supabase.invalidate_cache()
    env = {"SUPABASE_URL": "http://supabase.test", "SUPABASE_KEY": "k"}
    with mock.patch.dict(os.environ, env), \
         mock.patch("zero.memory_supabase.sb_request", fake):
        yield
    memory_supabase.invalidate_cache()


def _request_tipica(nombre: str) -> None:
    """Llama al endpoint de api.py tal cual lo haría el dashboard (bridge simulado)."""
    ready = {"state": "ready", "account": NUMERO, "chats": [], "messages": []}
    with mock.patch("zero.whatsapp_web.bridge_request", return_value=dict(ready)), \
         mock.patch("zero.client_integrations.whatsapp_provider", return_value="web"), \
         mock.patch("zero.whatsapp_event_review._database", return_value=None):
        fn = getattr(api, nombre)
        if nombre == "whatsapp_web_messages":
            fn("chat@c.us", 50, CLIENT)
        else:
            fn(CLIENT)


def medir_polling(fake: FakeSupabase, segundos: float = 3600.0) -> dict:
    """Simula `segundos` de polling del dashboard con reloj falso. Devuelve el egress."""
    reloj = [1000.0]
    with mock.patch("zero.memory_supabase.time.monotonic", lambda: reloj[0]):
        eventos = sorted((t, nombre) for nombre, cada in POLLING
                         for t in range(cada, int(segundos) + 1, cada))
        for t, nombre in eventos:
            reloj[0] = 1000.0 + t
            _request_tipica(nombre)
    return {"lecturas": fake.reads, "completas": fake.full_reads, "bytes": fake.bytes,
            "requests": len(eventos)}


@unittest.skipUnless(_API_AVAILABLE, "api.py necesita fastapi")
class TestEgressPolling(unittest.TestCase):
    def test_una_request_por_endpoint_y_polling_por_hora(self):
        estado = _estado_tipico()
        tam = len(json.dumps(estado))
        self.assertGreater(tam, 80_000)   # el fixture es del tamaño real, no uno de juguete
        for nombre in sorted({n for n, _ in POLLING}):
            fake = FakeSupabase(estado)
            with _nube(fake):
                _request_tipica(nombre)
            print(f"  {nombre}: {fake.reads} lecturas, {fake.bytes} bytes (1.ª request, caché vacía)")
        fake = FakeSupabase(estado)
        with _nube(fake):
            r = medir_polling(fake)
        print(f"  POLLING 1 h ({r['requests']} requests): {r['lecturas']} lecturas "
              f"({r['completas']} completas), {r['bytes'] / 1e6:.2f} MB")
        # Con la caché, el polling con el estado quieto baja la fila una sola vez.
        self.assertEqual(r["completas"], 1)
        self.assertLess(r["bytes"], 2 * tam)

    def test_escrituras_ajenas_se_ven_en_la_siguiente_carga(self):
        estado = _estado_tipico()
        fake = FakeSupabase(estado)
        with _nube(fake):
            reloj = [1000.0]
            reloj_falso = mock.patch("zero.memory_supabase.time.monotonic", lambda: reloj[0])
            reloj_falso.start()
            self.addCleanup(reloj_falso.stop)
            _request_tipica("whatsapp_attention")
            cambiado = copy.deepcopy(estado)
            cambiado["clients"][CLIENT]["agent_profile"]["whatsapp_number"] = "999"
            fake.external_write(cambiado)
            reloj[0] += MEMORY_CLOUD_CACHE_TTL_S + 0.1
            m = memory_supabase.SupabaseMemory()
            self.assertEqual(m.get_client_agent_profile(CLIENT)["whatsapp_number"], "999")


class TestCacheMemoria(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSupabase(_estado_tipico())
        ctx = _nube(self.fake)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.reloj = [1000.0]
        p = mock.patch("zero.memory_supabase.time.monotonic", lambda: self.reloj[0])
        p.start()
        self.addCleanup(p.stop)

    def test_rafaga_dentro_del_micro_ttl_no_hace_red(self):
        memory_supabase.SupabaseMemory()
        self.reloj[0] += MEMORY_CLOUD_CACHE_TTL_S / 2
        memory_supabase.SupabaseMemory()
        self.assertEqual((self.fake.full_reads, self.fake.version_reads), (1, 0))

    def test_cada_carga_valida_la_version_y_si_es_igual_no_baja_la_fila(self):
        memory_supabase.SupabaseMemory()
        for _ in range(5):
            self.reloj[0] += MEMORY_CLOUD_CACHE_TTL_S + 0.1
            memory_supabase.SupabaseMemory()
        self.assertEqual((self.fake.full_reads, self.fake.version_reads), (1, 5))

    def test_version_distinta_baja_la_fila_una_vez(self):
        memory_supabase.SupabaseMemory()
        ajeno = copy.deepcopy(self.fake.row["data"])
        ajeno["used_emails"] = ["otro@x.cl"]
        self.fake.external_write(ajeno)
        self.reloj[0] += MEMORY_CLOUD_CACHE_TTL_S + 0.1
        m = memory_supabase.SupabaseMemory()
        self.assertEqual(m.used_emails, ["otro@x.cl"])
        self.assertEqual((self.fake.full_reads, self.fake.version_reads), (2, 1))
        self.reloj[0] += MEMORY_CLOUD_CACHE_TTL_S + 0.1
        memory_supabase.SupabaseMemory()
        self.assertEqual(self.fake.full_reads, 2)

    def test_reload_y_fresh_bajan_la_fila_completa(self):
        a = memory_supabase.SupabaseMemory()
        ajeno = copy.deepcopy(self.fake.row["data"])
        ajeno["used_emails"] = ["otro@x.cl"]
        self.fake.external_write(ajeno)
        a.reload()                                     # sin avanzar el reloj: ignora el micro-TTL
        self.assertEqual(a.used_emails, ["otro@x.cl"])
        self.fake.external_write(_estado_tipico())
        self.assertEqual(memory_supabase.SupabaseMemory(fresh=True).used_emails, [])
        self.assertEqual(self.fake.full_reads, 3)

    def test_save_es_el_ultimo_que_escribe_gana(self):
        memory_supabase.SupabaseMemory()
        a = memory_supabase.SupabaseMemory()
        ajeno = copy.deepcopy(self.fake.row["data"])
        ajeno["used_emails"] = ["otro@x.cl"]
        self.fake.external_write(ajeno)
        a.add_used_email("mio@x.cl")
        a.save()                                       # sin 409: comportamiento previo
        self.assertEqual(self.fake.row["data"]["used_emails"], ["mio@x.cl"])
        self.assertEqual(self.fake.writes, 1)

    def test_el_lock_no_se_toma_durante_la_red(self):
        memory_supabase.SupabaseMemory()
        self.reloj[0] += MEMORY_CLOUD_CACHE_TTL_S + 0.1
        ambos_en_la_red = threading.Barrier(2, timeout=5)
        original = self.fake.__call__

        def lenta(base_url, key, method, path, body=None, **kw):
            if method == "GET" and path.endswith("select=updated"):
                ambos_en_la_red.wait()      # si el lock serializara, el 2.º nunca llega
            return original(base_url, key, method, path, body=body, **kw)
        errores = []

        def cargar():
            try:
                memory_supabase.SupabaseMemory()
            except Exception as e:   # noqa: BLE001 — se reporta abajo
                errores.append(e)
        with mock.patch("zero.memory_supabase.sb_request", lenta):
            hilos = [threading.Thread(target=cargar) for _ in range(2)]
            for h in hilos:
                h.start()
            for h in hilos:
                h.join(10)
        self.assertEqual(errores, [])
        self.assertTrue(memory_supabase._lock.acquire(timeout=1))
        memory_supabase._lock.release()

    def test_instancias_no_comparten_estructuras(self):
        a = memory_supabase.SupabaseMemory()
        a.set_client_agent_profile(CLIENT, {"whatsapp_number": "mutado"})   # sin save()
        b = memory_supabase.SupabaseMemory()
        self.assertEqual(b.get_client_agent_profile(CLIENT)["whatsapp_number"], NUMERO)

    def test_save_actualiza_la_caja_y_no_hay_relectura(self):
        a = memory_supabase.SupabaseMemory()
        a.set_client_agent_profile(CLIENT, {"whatsapp_number": "nuevo"})
        a.save()
        b = memory_supabase.SupabaseMemory()
        self.assertEqual(b.get_client_agent_profile(CLIENT)["whatsapp_number"], "nuevo")
        self.assertEqual(self.fake.full_reads, 1)
        self.assertEqual(self.fake.row["data"]["clients"][CLIENT]["agent_profile"]
                         ["whatsapp_number"], "nuevo")

    def test_supabase_caido_con_cache_llena_sirve_la_ultima_copia_y_loguea_antiguedad(self):
        memory_supabase.SupabaseMemory()
        self.reloj[0] += 42
        self.fake.down = True
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            m = memory_supabase.SupabaseMemory()
        self.assertEqual(m.get_client_agent_profile(CLIENT)["whatsapp_number"], NUMERO)
        self.assertIn("hace 42s", err.getvalue())
        m.add_used_email("x@x.cl")
        with self.assertRaises(SupabaseError):          # save() falla como antes mientras siga caído
            m.save()

    def test_supabase_caido_con_cache_vacia_falla_como_antes(self):
        self.fake.down = True
        with self.assertRaises(SupabaseError):
            memory_supabase.SupabaseMemory()

    def test_fresh_con_supabase_caido_no_sirve_cache(self):
        memory_supabase.SupabaseMemory()
        self.fake.down = True
        with self.assertRaises(SupabaseError):
            memory_supabase.SupabaseMemory(fresh=True)

    def test_fila_inexistente_se_cachea(self):
        self.fake.row = None
        fake = self.fake
        original = fake.__call__

        def sin_fila(base_url, key, method, path, body=None, **kw):
            if method == "GET":
                fake.full_reads += 1
                return []
            return original(base_url, key, method, path, body=body, **kw)
        with mock.patch("zero.memory_supabase.sb_request", sin_fila):
            memory_supabase.SupabaseMemory()
            memory_supabase.SupabaseMemory()
        self.assertEqual(fake.full_reads, 1)


class TestVersion(unittest.TestCase):
    def test_misma_hora_en_distinto_formato_es_la_misma_version(self):
        a = "2026-11-27T10:00:00.120000+00:00"
        b = "2026-11-27T10:00:00.12+00:00"
        self.assertTrue(memory_supabase._same_version(a, b))
        self.assertFalse(memory_supabase._same_version(a, None))
        self.assertFalse(memory_supabase._same_version(
            a, (datetime.fromisoformat(a) + timedelta(microseconds=1)).isoformat()))


if __name__ == "__main__":
    unittest.main()
