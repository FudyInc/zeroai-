"""scripts/reconciliar_estado.py — fusión nube + state.json local.

Nube simulada (`FakeSupabase` de test_memoria_cache, inyectada en el script): sin red real,
sin tocar state.json / crm.json / ~/respaldos reales (todo en temporales).

Correr solo:  python3 -m unittest tests.test_reconciliar_estado -v
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zero import estado_retenido

from tests.test_memoria_cache import FakeSupabase

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("reconciliar_estado",
                                               REPO / "scripts" / "reconciliar_estado.py")
rec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rec)

T0 = "2026-11-20T10:00:00+00:00"      # antes del corte
CORTE = "2026-11-25T21:55:00+00:00"
T1 = "2026-11-26T10:00:00+00:00"      # durante la caída
T2 = "2026-11-27T10:00:00+00:00"


def fusionar(nube, local, **kw):
    return rec.fusionar(copy.deepcopy(nube), copy.deepcopy(local), CORTE, **kw)


def rutas(f):
    return {c["ruta"]: c for c in f.conflictos}


class TestReglasPorClave(unittest.TestCase):
    def test_actions_union_sin_duplicados_ordenada(self):
        comun = {"ts": T0, "action": "a"}
        nube = {"actions": [comun, {"ts": T1, "action": "n"}]}
        local = {"actions": [comun, {"ts": "2026-11-21T00:00:00+00:00", "action": "l"}]}
        out, f = fusionar(nube, local)
        self.assertEqual([a["action"] for a in out["actions"]], ["a", "l", "n"])
        self.assertEqual(f.stats["actions"], {"de_local": 1, "solo_nube": 1, "iguales": 1,
                                              "fusionados": 0})

    def test_used_emails_union(self):
        out, _ = fusionar({"used_emails": ["a@x", "b@x"]}, {"used_emails": ["b@x", "c@x"]})
        self.assertEqual(out["used_emails"], ["a@x", "b@x", "c@x"])

    def test_contacted_gana_el_mas_reciente(self):
        nube = {"contacted": {"x": T1, "y": T0}, "contacted_by_client": {"acme": {"x": T0}}}
        local = {"contacted": {"x": T0, "z": T0}, "contacted_by_client": {"acme": {"x": T2, "w": T0}}}
        out, f = fusionar(nube, local)
        self.assertEqual(out["contacted"], {"x": T1, "y": T0, "z": T0})
        self.assertEqual(out["contacted_by_client"], {"acme": {"x": T2, "w": T0}})
        self.assertEqual(f.conflictos, [])

    def test_sequences_cerrada_gana_a_abierta_y_mayor_step(self):
        base = {"client_id": "acme", "lead_key": "a", "started": T0, "status": "open", "step": 0}
        cerrada = dict(base, status="closed", next_due=None, closed_reason="replied")
        otra = {"client_id": "acme", "lead_key": "b", "started": T0, "status": "open", "step": 1}
        out, f = fusionar({"sequences": [base, otra]},
                          {"sequences": [cerrada, dict(otra, step=2)]})
        por_lead = {s["lead_key"]: s for s in out["sequences"]}
        self.assertEqual(por_lead["a"]["status"], "closed")
        self.assertEqual(por_lead["b"]["step"], 2)
        self.assertEqual(f.conflictos, [])

    def test_sequences_empate_con_contenido_distinto_es_conflicto_nube(self):
        a = {"client_id": "acme", "lead_key": "a", "started": T0, "status": "open", "step": 1,
             "next_due": T1}
        out, f = fusionar({"sequences": [a]}, {"sequences": [dict(a, next_due=T2)]})
        self.assertEqual(out["sequences"][0]["next_due"], T1)
        self.assertEqual(len(f.conflictos), 1)

    def test_sequences_dos_abiertas_del_mismo_lead_se_cierra_la_mas_nueva(self):
        nube = {"sequences": [{"client_id": "acme", "lead_key": "a", "started": T0,
                               "status": "open", "step": 0}]}
        local = {"sequences": [{"client_id": "acme", "lead_key": "a", "started": T1,
                                "status": "open", "step": 0, "next_due": T2}]}
        out, f = fusionar(nube, local)
        estados = {s["started"]: s for s in out["sequences"]}
        self.assertEqual(estados[T0]["status"], "open")
        self.assertEqual(estados[T1]["status"], "closed")
        self.assertEqual(estados[T1]["closed_reason"], "fusion_duplicada")
        self.assertIsNone(estados[T1]["next_due"])
        self.assertEqual(len(f.conflictos), 1)

    def test_pending_offers_gana_la_mas_reciente(self):
        nube = {"pending_offers": {"acme|a": {"kind": "resumen", "ts": T0},
                                   "acme|b": {"kind": "k", "ts": T0}}}
        local = {"pending_offers": {"acme|a": {"kind": "ejemplos", "ts": T1},
                                    "acme|c": {"kind": "k", "ts": T1}}}
        out, f = fusionar(nube, local)
        self.assertEqual(out["pending_offers"]["acme|a"]["kind"], "ejemplos")
        self.assertEqual(set(out["pending_offers"]), {"acme|a", "acme|b", "acme|c"})
        self.assertEqual(f.conflictos, [])

    def test_agent_status_difiere_conflicto_nube(self):
        out, f = fusionar({"agent_status": {"X": "ok"}}, {"agent_status": {"X": "fail", "Y": "ok"}})
        self.assertEqual(out["agent_status"], {"X": "ok", "Y": "ok"})
        self.assertIn("agent_status.X", rutas(f))

    def test_vendors_y_functions_union_por_id_y_campo(self):
        nube = {"vendors": {"v1": {"id": "v1", "name": "A"}}, "functions": {"f1": {"id": "f1", "x": 1}}}
        local = {"vendors": {"v1": {"id": "v1", "name": "B", "phone": "1"}, "v2": {"id": "v2"}},
                 "functions": {"f1": {"id": "f1", "x": 1}}}
        out, f = fusionar(nube, local)
        self.assertEqual(out["vendors"]["v1"], {"id": "v1", "name": "A", "phone": "1"})
        self.assertIn("v2", out["vendors"])
        self.assertEqual(list(rutas(f)), ["vendors.v1.name"])

    def test_clave_desconocida_se_lista_y_no_se_toca(self):
        out, f = fusionar({"rara": 1, "actions": []}, {"rara": 2, "solo_local": 3, "actions": []})
        self.assertEqual(out["rara"], 1)
        self.assertNotIn("solo_local", out)
        self.assertEqual(set(rutas(f)), {"rara", "solo_local"})


class TestClients(unittest.TestCase):
    def test_union_por_id_y_campo_conflictivo_conserva_nube(self):
        nube = {"clients": {"acme": {"tier": "GROWTH", "icp": {"a": 1}, "stage": "registered"}}}
        local = {"clients": {"acme": {"tier": "GROWTH", "icp": {"a": 2}, "pricing": {"p": 1}},
                             "beta": {"tier": "STARTER"}}}
        out, f = fusionar(nube, local)
        self.assertEqual(out["clients"]["acme"]["icp"], {"a": 1})
        self.assertEqual(out["clients"]["acme"]["pricing"], {"p": 1})
        self.assertEqual(out["clients"]["acme"]["stage"], "registered")
        self.assertIn("beta", out["clients"])
        self.assertEqual(list(rutas(f)), ["clients.acme.icp"])

    def test_local_fuerza_el_valor_local_en_ese_conflicto(self):
        nube = {"clients": {"acme": {"icp": {"a": 1}}}}
        local = {"clients": {"acme": {"icp": {"a": 2}}}}
        out, f = fusionar(nube, local, locales=("clients.acme.icp",))
        self.assertEqual(out["clients"]["acme"]["icp"], {"a": 2})
        self.assertEqual(f.conflictos[0]["resolucion"], "local (forzado)")

    def test_conversaciones_union_ordenada_sin_duplicados(self):
        t = lambda role, text, at: {"role": role, "text": text, "at": at}  # noqa: E731
        nube = {"clients": {"acme": {"conversations": {"569": [t("lead", "hola", T0), t("agent", "hi", T1)]}}}}
        local = {"clients": {"acme": {"conversations": {
            "569": [t("lead", "hola", T0), t("lead", "precio?", T2)], "570": [t("lead", "x", T1)]}}}}
        out, f = fusionar(nube, local)
        conv = out["clients"]["acme"]["conversations"]
        self.assertEqual([x["text"] for x in conv["569"]], ["hola", "hi", "precio?"])
        self.assertEqual(len(conv["570"]), 1)
        self.assertEqual(f.conflictos, [])

    def test_conversaciones_respetan_el_tope(self):
        from zero.memory import SessionMemory
        tope = SessionMemory.MAX_TURNS_STORED
        nube = {"clients": {"a": {"conversations": {"k": [
            {"role": "lead", "text": f"n{i}", "at": f"2026-11-01T00:{i // 60:02d}:{i % 60:02d}+00:00"}
            for i in range(tope)]}}}}
        local = {"clients": {"a": {"conversations": {"k": [
            {"role": "lead", "text": "ultimo", "at": T2}]}}}}
        out, _ = fusionar(nube, local)
        turnos = out["clients"]["a"]["conversations"]["k"]
        self.assertEqual(len(turnos), tope)
        self.assertEqual(turnos[-1]["text"], "ultimo")

    def test_huecos_gana_el_evento_mas_reciente(self):
        nube = {"clients": {"acme": {"knowledge_gaps": {"despacho": {
            "pregunta": "despacho?", "veces": 5, "primera": T0, "ultima": T0, "estado": "abierta",
            "esperando": [{"chat_id": "c1", "at": T0}]}}}}}
        local = {"clients": {"acme": {"knowledge_gaps": {"despacho": {
            "pregunta": "despacho?", "veces": 2, "primera": T1, "ultima": T1, "estado": "resuelta",
            "resuelta_en": T2, "respuesta": "si", "esperando": []}}}}}
        out, f = fusionar(nube, local)
        h = out["clients"]["acme"]["knowledge_gaps"]["despacho"]
        self.assertEqual((h["estado"], h["respuesta"], h["veces"], h["primera"]),
                         ("resuelta", "si", 5, T0))
        self.assertEqual(h["esperando"], [])
        self.assertEqual(f.conflictos, [])

    def test_huecos_abiertos_unen_esperando_por_chat(self):
        nube = {"clients": {"a": {"knowledge_gaps": {"k": {
            "veces": 1, "ultima": T0, "estado": "abierta",
            "esperando": [{"chat_id": "c1", "at": T0}]}}}}}
        local = {"clients": {"a": {"knowledge_gaps": {"k": {
            "veces": 2, "ultima": T1, "estado": "abierta",
            "esperando": [{"chat_id": "c1", "at": T1}, {"chat_id": "c2", "at": T1}]}}}}}
        out, _ = fusionar(nube, local)
        esperando = out["clients"]["a"]["knowledge_gaps"]["k"]["esperando"]
        self.assertEqual([e["chat_id"] for e in esperando], ["c1", "c2"])
        self.assertEqual(esperando[0]["at"], T1)

    def test_huecos_sin_marca_de_tiempo_es_conflicto(self):
        nube = {"clients": {"a": {"knowledge_gaps": {"k": {"estado": "abierta", "veces": 1}}}}}
        local = {"clients": {"a": {"knowledge_gaps": {"k": {"estado": "resuelta", "veces": 1}}}}}
        out, f = fusionar(nube, local)
        self.assertEqual(out["clients"]["a"]["knowledge_gaps"]["k"]["estado"], "abierta")
        self.assertEqual(len(f.conflictos), 1)

    def test_pausas_whatsapp_gana_la_mas_reciente_y_una_sola_se_conserva(self):
        nube = {"clients": {"a": {"whatsapp_handoffs": {"1": {"reason": "n", "at": T0},
                                                        "2": {"reason": "solo nube", "at": T0}}}}}
        local = {"clients": {"a": {"whatsapp_handoffs": {"1": {"reason": "l", "at": T1}}}}}
        out, f = fusionar(nube, local)
        pausas = out["clients"]["a"]["whatsapp_handoffs"]
        self.assertEqual(pausas["1"]["reason"], "l")
        self.assertEqual(pausas["2"]["reason"], "solo nube")
        self.assertEqual(f.conflictos, [])

    def test_notas_de_lead_union_y_conflicto_en_valor(self):
        nube = {"clients": {"a": {"lead_notes": {"1": {"x": 1, "y": 1}}}}}
        local = {"clients": {"a": {"lead_notes": {"1": {"x": 1, "y": 2, "z": 3}}}}}
        out, f = fusionar(nube, local)
        self.assertEqual(out["clients"]["a"]["lead_notes"]["1"], {"x": 1, "y": 1, "z": 3})
        self.assertEqual(list(rutas(f)), ["clients.a.lead_notes.1.y"])


def _v(n, texto, at):
    return {"version": n, "knowledge": texto, "chars": len(texto), "guardada": at, "motivo": ""}


class TestFichas(unittest.TestCase):
    def test_union_de_versiones_y_vigente_la_mas_reciente(self):
        nube = {"clients": {"a": {"knowledge": "v2", "knowledge_version": 2,
                                  "knowledge_versions": [_v(1, "v1", T0), _v(2, "v2", T0)]}}}
        local = {"clients": {"a": {"knowledge": "v3", "knowledge_version": 3,
                                   "knowledge_versions": [_v(1, "v1", T0), _v(2, "v2", T0),
                                                          _v(3, "v3", T1)]}}}
        out, f = fusionar(nube, local)
        ficha = out["clients"]["a"]
        self.assertEqual((ficha["knowledge"], ficha["knowledge_version"]), ("v3", 3))
        self.assertEqual([v["version"] for v in ficha["knowledge_versions"]], [1, 2, 3])
        self.assertEqual(f.conflictos, [])

    def test_mismo_numero_distinto_texto_se_renumera_y_conserva_ambas(self):
        nube = {"clients": {"a": {"knowledge": "n4", "knowledge_version": 4,
                                  "knowledge_versions": [_v(3, "v3", T0), _v(4, "n4", T0)]}}}
        local = {"clients": {"a": {"knowledge": "l4", "knowledge_version": 4,
                                   "knowledge_versions": [_v(3, "v3", T0), _v(4, "l4", T1)]}}}
        out, f = fusionar(nube, local)
        ficha = out["clients"]["a"]
        self.assertEqual([(v["version"], v["knowledge"]) for v in ficha["knowledge_versions"]],
                         [(3, "v3"), (4, "n4"), (5, "l4")])
        self.assertEqual((ficha["knowledge"], ficha["knowledge_version"]), ("l4", 5))
        self.assertEqual(len(f.conflictos), 1)

    def test_ficha_sin_historial_en_un_lado_se_siembra(self):
        nube = {"clients": {"a": {"knowledge": "otra"}}}
        local = {"clients": {"a": {"knowledge": "nueva", "knowledge_version": 2,
                                   "knowledge_versions": [_v(1, "vieja", T0), _v(2, "nueva", T1)]}}}
        out, _ = fusionar(nube, local)
        ficha = out["clients"]["a"]
        self.assertEqual(ficha["knowledge"], "nueva")
        self.assertEqual([v["knowledge"] for v in ficha["knowledge_versions"]],
                         ["otra", "vieja", "nueva"])             # la sembrada queda la más vieja
        self.assertEqual(ficha["knowledge_version"], 3)

    def test_tope_de_versiones_no_tira_la_vigente(self):
        with mock.patch.object(rec, "MAX_KNOWLEDGE_VERSIONS", 2):
            nube = {"clients": {"a": {"knowledge": "v2", "knowledge_version": 2,
                                      "knowledge_versions": [_v(1, "v1", T0), _v(2, "v2", T0)]}}}
            local = {"clients": {"a": {"knowledge": "v3", "knowledge_version": 3,
                                       "knowledge_versions": [_v(3, "v3", T1)]}}}
            out, _ = fusionar(nube, local)
        self.assertEqual([v["version"] for v in out["clients"]["a"]["knowledge_versions"]], [2, 3])
        self.assertEqual(out["clients"]["a"]["knowledge"], "v3")

    def test_fusion_es_idempotente(self):
        nube = {"clients": {"a": {"knowledge": "n4", "knowledge_version": 4,
                                  "knowledge_versions": [_v(4, "n4", T0)]}}, "actions": [{"ts": T0}]}
        local = {"clients": {"a": {"knowledge": "l4", "knowledge_version": 4,
                                   "knowledge_versions": [_v(4, "l4", T1)]}}, "actions": [{"ts": T1}]}
        una, _ = fusionar(nube, local)
        dos, f = fusionar(una, una)
        self.assertEqual(rec._c(una), rec._c(dos))
        self.assertEqual(f.conflictos, [])


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.state = self.dir / "state.json"
        self.respaldos = self.dir / "respaldos"
        self.marca = self.dir / ".runtime" / "estado-local-retenido.json"
        self.nube_inicial = {"clients": {"acme": {"tier": "GROWTH"}}, "actions": [{"ts": T0, "action": "n"}]}
        self.local_inicial = {"clients": {"acme": {"tier": "GROWTH"}, "beta": {"tier": "STARTER"}},
                              "actions": [{"ts": T1, "action": "l"}]}
        self.state.write_text(json.dumps(self.local_inicial), "utf-8")
        self.nube = FakeSupabase(self.nube_inicial)
        env = {"SUPABASE_URL": "http://supabase.test", "SUPABASE_KEY": "k",
               "ZERO_ESTADO_RETENIDO_PATH": str(self.marca)}
        for p in (mock.patch.dict(os.environ, env),
                  mock.patch.object(rec, "sb_request", self.nube),
                  mock.patch.object(rec, "ESTADO_RESPALDOS_DIR", str(self.respaldos))):
            p.start()
            self.addCleanup(p.stop)
        estado_retenido.marcar("402")

    def correr(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            codigo = rec.main(["--state", str(self.state), *args])
        return codigo, out.getvalue(), err.getvalue()


class TestScript(Base):
    def test_dry_run_no_escribe_nada(self):
        antes_state = self.state.read_text("utf-8")
        antes_nube = copy.deepcopy(self.nube.row)
        codigo, salida, _ = self.correr()
        self.assertEqual(codigo, 0)
        self.assertIn("DRY-RUN", salida)
        self.assertIn("actions", salida)
        self.assertEqual(self.state.read_text("utf-8"), antes_state)
        self.assertEqual(self.nube.row, antes_nube)
        self.assertEqual(self.nube.writes, 0)
        self.assertFalse(self.respaldos.exists())
        self.assertTrue(self.marca.exists())

    def test_nube_caida_sale_con_2_sin_tocar_nada(self):
        self.nube.down = True
        antes_state = self.state.read_text("utf-8")
        for args in ((), ("--aplicar", "--si")):
            codigo, _, err = self.correr(*args)
            self.assertEqual(codigo, 2)
            self.assertIn("aún no responde", err)
        self.assertEqual(self.state.read_text("utf-8"), antes_state)
        self.assertEqual(self.nube.writes, 0)
        self.assertFalse(self.respaldos.exists())
        self.assertTrue(self.marca.exists())

    def test_aplicar_respalda_antes_de_escribir(self):
        orden = []
        escribir = self.nube.__call__

        def espia(base, key, method, path, **kw):
            if method == "POST":
                orden.append(("nube", [p.name for p in self.respaldos.glob("*/*.json")]))
            return escribir(base, key, method, path, **kw)

        with mock.patch.object(rec, "sb_request", espia):
            codigo, _, _ = self.correr("--aplicar", "--si")
        self.assertEqual(codigo, 0)
        self.assertEqual(sorted(orden[0][1]), ["local.json", "nube.json"])   # ya estaban al escribir
        carpeta = next(self.respaldos.iterdir())
        self.assertTrue(carpeta.name.startswith("estado-reconciliacion-"))
        self.assertEqual(json.loads((carpeta / "nube.json").read_text()), self.nube_inicial)
        self.assertEqual(json.loads((carpeta / "local.json").read_text()), self.local_inicial)
        for archivo in carpeta.glob("*.json"):
            self.assertEqual(stat.S_IMODE(archivo.stat().st_mode), 0o600)

    def test_aplicar_escribe_nube_y_local_y_libera_el_marcador_al_final(self):
        codigo, salida, _ = self.correr("--aplicar", "--si")
        self.assertEqual(codigo, 0)
        local = json.loads(self.state.read_text("utf-8"))
        self.assertEqual(rec._c(local), rec._c(self.nube.row["data"]))
        self.assertEqual({a["action"] for a in local["actions"]}, {"n", "l"})
        self.assertIn("beta", local["clients"])
        self.assertFalse(self.marca.exists())
        self.assertEqual(self.nube.writes, 1)

    def test_marcador_sobrevive_si_falla_la_escritura_de_la_nube(self):
        original = self.nube.__call__

        def falla_al_escribir(base, key, method, path, **kw):
            if method == "POST":
                raise rec.SupabaseError("Supabase 402", code=402)
            return original(base, key, method, path, **kw)

        antes_state = self.state.read_text("utf-8")
        with mock.patch.object(rec, "sb_request", falla_al_escribir):
            codigo, _, err = self.correr("--aplicar", "--si")
        self.assertEqual(codigo, 2)
        self.assertTrue(self.marca.exists())
        self.assertEqual(self.state.read_text("utf-8"), antes_state)    # local intacto
        self.assertTrue(any(self.respaldos.glob("*/nube.json")))        # el respaldo quedó

    def test_marcador_sobrevive_si_falla_el_state_local(self):
        with mock.patch.object(rec, "save_json", side_effect=OSError("disco lleno")):
            codigo, _, _ = self.correr("--aplicar", "--si")
        self.assertEqual(codigo, 1)
        self.assertTrue(self.marca.exists())

    def test_aborta_si_la_nube_cambio_durante_el_calculo(self):
        original = self.nube.__call__
        llamadas = {"n": 0}

        def cambia(base, key, method, path, **kw):
            llamadas["n"] += 1
            if llamadas["n"] == 2:     # justo antes de escribir: otro proceso toca la fila
                self.nube.external_write({"clients": {}})
            return original(base, key, method, path, **kw)

        with mock.patch.object(rec, "sb_request", cambia):
            codigo, _, err = self.correr("--aplicar", "--si")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.nube.writes, 0)
        self.assertTrue(self.marca.exists())

    def test_confirmacion_interactiva(self):
        with mock.patch("builtins.input", return_value="no"):
            codigo, _, err = self.correr("--aplicar")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.nube.writes, 0)
        self.assertTrue(self.marca.exists())
        with mock.patch("builtins.input", return_value="SI"):
            codigo, _, _ = self.correr("--aplicar")
        self.assertEqual(codigo, 0)
        self.assertFalse(self.marca.exists())

    def test_state_corrupto_no_se_toca(self):
        self.state.write_text("{corrupto", "utf-8")
        codigo, _, err = self.correr("--aplicar", "--si")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.state.read_text("utf-8"), "{corrupto")
        self.assertEqual(self.nube.writes, 0)

    def test_nube_sin_fila_toma_lo_local(self):
        self.nube.row = None
        original = self.nube.__call__

        def sin_fila(base, key, method, path, **kw):
            if method == "GET" and self.nube.row is None:
                return []
            return original(base, key, method, path, **kw)

        with mock.patch.object(rec, "sb_request", sin_fila):
            codigo, _, _ = self.correr()
        self.assertEqual(codigo, 0)


if __name__ == "__main__":
    unittest.main()
