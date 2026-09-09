"""Las dos rutas que hacen visible al ciclo autónomo: /api/ciclo/estado y /api/ciclo/salud.

Estos tests están escritos al revés de lo habitual: **el camino feliz es lo de menos.**

El motivo está medido. Entre el 2026-08-29 y el 2026-09-05 el ciclo estuvo ocho días sin
ejecutar una sola tarea, con la suite en verde y `hallazgos: 0` todos los días. Lo que
falló no fue la lógica, fue la instrumentación: un aviso que no salía con la máquina
muerta, y otro que salía con confianza sobre algo falso. La conclusión quedó anotada como
`[[zero-instrumentation-lesson]]`: **toda señal nueva necesita una prueba de su modo de
fallo, no solo de su camino feliz.**

Estas rutas SON una señal nueva. Si /api/ciclo/salud devuelve 200 con la lista vacía
porque git falló, y el dashboard pinta "sin hallazgos", el sistema vuelve a mentir
exactamente igual que en agosto — con la diferencia de que ahora la mentira tiene una
pantalla bonita. Por eso lo que se fija acá es que **degradar sea distinguible de estar
sano**: `disponible: false` y un `motivo` legible, nunca una lista vacía silenciosa.

Run: python3 -m unittest tests.test_ciclo_endpoint -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _api():
    """api.py se importa dentro de cada test, como en test_whatsapp_engine.py: importarlo
    a nivel de módulo levanta env, secretos de nube y la app entera para toda la suite."""
    import api
    return api


class AuditoriaDeHoy(unittest.TestCase):
    """`_auditoria_de_hoy()` lee auditoria.json, que está gitignorado y lo reescribe
    auditar.py en cada corrida. O sea: puede no existir, puede estar a medio escribir, y
    puede tener cualquier forma. Ninguno de esos casos puede tumbar la respuesta."""

    def setUp(self):
        self.api = _api()
        self.dir = tempfile.mkdtemp()
        self.previo = os.getcwd()
        os.chdir(self.dir)          # la función lee Path("auditoria.json"), relativo al cwd

    def tearDown(self):
        os.chdir(self.previo)

    def test_sin_archivo_devuelve_none(self):
        """El caso normal en una máquina donde el ciclo nunca corrió."""
        self.assertIsNone(self.api._auditoria_de_hoy())

    def test_json_corrupto_devuelve_none_en_vez_de_reventar(self):
        """auditar.py escribe el archivo entero de una vez, pero un corte de luz a mitad
        deja JSON truncado. Eso no puede ser un 500 en el dashboard."""
        Path("auditoria.json").write_text('{"cuando": 123, "hallaz', encoding="utf-8")
        self.assertIsNone(self.api._auditoria_de_hoy())

    def test_json_valido_pero_no_es_un_objeto(self):
        """Defensa contra la forma, no solo contra el parseo: `[]` es JSON válido."""
        Path("auditoria.json").write_text("[]", encoding="utf-8")
        self.assertIsNone(self.api._auditoria_de_hoy())

    def test_resume_en_vez_de_volcar_el_informe_entero(self):
        """La respuesta del ciclo no es lugar para el informe completo: de cada check
        viaja el nombre y cuántos hallazgos tuvo, no su `evidencia` ni su `extra`."""
        Path("auditoria.json").write_text(json.dumps({
            "cuando": 1788637000.0,
            "checks": [{"check": "suite de tests", "hallazgos": 0, "segundos": 20.5},
                       {"check": "build del dashboard", "hallazgos": 1, "segundos": 4.6}],
            "hallazgos": [
                {"check": "build", "gravedad": "alta", "detalle": "no compila",
                 "evidencia": "npm run build", "extra": "x" * 5000},
                {"check": "ficha", "gravedad": "media", "detalle": "se trunca",
                 "evidencia": "wc -c"},
            ],
        }), encoding="utf-8")

        d = self.api._auditoria_de_hoy()
        self.assertEqual(d["hallazgos"], 2)
        self.assertEqual(d["altos"], 1)              # solo la de gravedad alta
        self.assertEqual([c["check"] for c in d["checks"]],
                         ["suite de tests", "build del dashboard"])
        self.assertNotIn("extra", json.dumps(d))     # el volcado grande no viaja


class HistorialDeSalud(unittest.TestCase):
    """`_informes_de_salud()` lee la rama `audit/diaria` con plumbing. Git puede no estar,
    la rama puede no existir y un informe puede estar corrupto — y el dashboard tiene que
    poder distinguir cada uno de esos casos de "todo bien"."""

    def setUp(self):
        self.api = _api()
        self.api._informes_cache.clear()   # la caché es de módulo: sin esto los tests se contaminan

    def tearDown(self):
        self.api._informes_cache.clear()

    def test_rama_inexistente_no_es_un_error_pero_tampoco_es_silencio(self):
        """**El test que justifica que la rama sea configurable.**

        Es el modo de fallo más probable en una máquina nueva: el ciclo todavía no
        archivó nada. Responder lista vacía sin motivo haría que el dashboard pinte
        "sin hallazgos" — indistinguible de una semana sana. Tiene que decir por qué.
        """
        with mock.patch.object(self.api, "CICLO_RAMA_SALUD", "audit/rama-que-no-existe"):
            informes, motivo = self.api._informes_de_salud(14)
        self.assertEqual(informes, [])
        self.assertTrue(motivo, "una lista vacía sin motivo es exactamente la mentira de agosto")
        self.assertIn("audit/rama-que-no-existe", motivo)

    def test_git_caido_degrada_con_motivo_y_no_lanza(self):
        """Si git no está instalado o el timeout salta, `_git_lectura` devuelve el error
        en vez de propagar la excepción — un endpoint de monitoreo no puede caerse."""
        with mock.patch.object(self.api, "_git_lectura",
                               return_value=("", "no se pudo consultar git (timeout)")):
            informes, motivo = self.api._informes_de_salud(14)
        self.assertEqual(informes, [])
        self.assertIn("timeout", motivo)

    def test_git_lectura_nunca_lanza_aunque_el_proceso_falle(self):
        with mock.patch("subprocess.run", side_effect=OSError("sin git")):
            salida, error = self.api._git_lectura("ls-tree", "loquesea")
        self.assertEqual(salida, "")
        self.assertIn("sin git", error)

    # --- lectura de informes reales, con git simulado --------------------------------
    def _ls_tree(self, *fechas: str) -> str:
        return "".join(
            f"100644 blob sha-{f}\tdocs/auditoria/{f}.json\n" for f in fechas)

    def _informe(self, altos: int = 0) -> str:
        return json.dumps({
            "cuando": 1788637000.0,
            "checks": [{"check": "suite de tests", "hallazgos": 0, "segundos": 20.0}],
            "hallazgos": [{"check": "tests", "gravedad": "alta", "detalle": "roja",
                           "evidencia": "python3 -m unittest"}] * altos,
        })

    def test_devuelve_del_mas_nuevo_al_mas_viejo_y_respeta_el_tope(self):
        """El dashboard muestra los últimos N días; el orden importa porque lo pinta tal
        cual viene."""
        def falso(*args):
            if args[0] == "ls-tree":
                return self._ls_tree("2026-09-01", "2026-09-05", "2026-09-03"), ""
            return self._informe(), ""

        with mock.patch.object(self.api, "_git_lectura", side_effect=falso):
            informes, motivo = self.api._informes_de_salud(2)
        self.assertEqual(motivo, "")
        self.assertEqual([i["fecha"] for i in informes], ["2026-09-05", "2026-09-03"])

    def test_un_informe_corrupto_no_se_lleva_a_los_demas(self):
        """Ocho días de historial no se pueden perder porque uno quedó a medio escribir."""
        def falso(*args):
            if args[0] == "ls-tree":
                return self._ls_tree("2026-09-04", "2026-09-05"), ""
            return ("{roto", "") if "2026-09-05" in args[1] else (self._informe(), "")

        with mock.patch.object(self.api, "_git_lectura", side_effect=falso):
            informes, _ = self.api._informes_de_salud(14)
        self.assertEqual([i["fecha"] for i in informes], ["2026-09-04"])

    def test_cuenta_los_altos_por_separado(self):
        """`hallazgos: 3` con 0 altos y `hallazgos: 3` con 3 altos son días muy distintos;
        el resumen no puede colapsarlos en un solo número."""
        def falso(*args):
            if args[0] == "ls-tree":
                return self._ls_tree("2026-09-05"), ""
            return self._informe(altos=2), ""

        with mock.patch.object(self.api, "_git_lectura", side_effect=falso):
            informes, _ = self.api._informes_de_salud(14)
        self.assertEqual((informes[0]["hallazgos"], informes[0]["altos"]), (2, 2))
        self.assertEqual(len(informes[0]["altos_detalle"]), 2)

    def test_la_cache_se_indexa_por_sha_no_por_fecha(self):
        """Un informe pasado no cambia, así que se cachea. Pero si alguien reescribe el
        archivo, el sha cambia y la caché tiene que fallar el hit — si se indexara por
        fecha, el dashboard mostraría para siempre la primera versión que leyó."""
        llamadas = []

        def falso(*args, sha="sha-v1", cuerpo=None):
            llamadas.append(args)
            if args[0] == "ls-tree":
                return f"100644 blob {sha}\tdocs/auditoria/2026-09-05.json\n", ""
            return cuerpo or self._informe(), ""

        with mock.patch.object(self.api, "_git_lectura", side_effect=falso):
            self.api._informes_de_salud(14)
            self.api._informes_de_salud(14)          # segunda vez: debe pegar en caché
        shows = [a for a in llamadas if a[0] == "show"]
        self.assertEqual(len(shows), 1, "el segundo llamado no usó la caché")

        # Mismo día, sha distinto: el informe se reescribió y hay que releerlo.
        llamadas.clear()
        with mock.patch.object(
                self.api, "_git_lectura",
                side_effect=lambda *a: falso(*a, sha="sha-v2", cuerpo=self._informe(altos=1))):
            informes, _ = self.api._informes_de_salud(14)
        self.assertEqual(len([a for a in llamadas if a[0] == "show"]), 1,
                         "el sha cambió y aun así no releyó el informe")
        self.assertEqual(informes[0]["altos"], 1, "la caché sirvió una versión vieja")


class LimitesYSuperficie(unittest.TestCase):
    """Los topes y lo que estas rutas exponen. Son de solo lectura sobre datos del
    negocio, así que lo que importa es que no se puedan usar para tumbar el backend ni
    para leer sin credenciales."""

    def setUp(self):
        self.api = _api()

    def test_un_limite_absurdo_no_intenta_servir_todo(self):
        """`?tareas=999999` no puede volcar la cola entera ni reventar por memoria."""
        r = self.api.ciclo_estado(tareas=999999, eventos=999999)
        self.assertLessEqual(len(r["tareas"]), 200)
        self.assertLessEqual(len(r["telemetria"]["eventos"]), 200)

    def test_un_limite_negativo_o_cero_no_rompe(self):
        r = self.api.ciclo_estado(tareas=0, eventos=-5)
        self.assertGreaterEqual(len(r["tareas"]), 0)
        self.assertEqual(r["telemetria"]["eventos"], [])

    def test_los_dias_se_topan_en_el_maximo(self):
        """Sin tope, `?dias=100000` haría un `git show` por informe hasta agotar la rama."""
        with mock.patch.object(self.api, "_informes_de_salud",
                               return_value=([], "")) as leer:
            r = self.api.ciclo_salud(dias=100000)
        self.assertEqual(r["dias"], self.api.CICLO_MAX_DIAS)
        leer.assert_called_once_with(self.api.CICLO_MAX_DIAS)

    def test_no_son_publicas(self):
        """Exponen la cola de trabajo y la telemetría de los agentes. `_OPEN_PATHS` es la
        lista de rutas sin login; estas no pueden estar ahí ni por descuido."""
        for ruta in ("/api/ciclo/estado", "/api/ciclo/salud"):
            self.assertNotIn(ruta, self.api._OPEN_PATHS)

    def test_son_admin_only_por_fail_closed(self):
        """No aparecer en `_ROLE_ALLOWED` no es un olvido: es lo que las deja en
        admin-only, igual que /api/functions/*. Este test fija esa decisión, para que
        agregarlas ahí después sea deliberado y no accidental."""
        permitidas = {ruta for rutas in self.api._ROLE_ALLOWED.values()
                      for _metodo, ruta in rutas}
        self.assertNotIn("/api/ciclo/estado", permitidas)
        self.assertNotIn("/api/ciclo/salud", permitidas)

    def test_el_estado_no_ofrece_forma_de_escribir(self):
        """La cola es dato local y vivo. Estas rutas solo leen: si alguna vez aparece un
        POST/DELETE bajo /api/ciclo, que sea una decisión y no un descuido."""
        metodos = {(m, r.path) for r in self.api.app.routes
                   for m in getattr(r, "methods", set())
                   if getattr(r, "path", "").startswith("/api/ciclo")}
        self.assertTrue(metodos)
        self.assertEqual({m for m, _ in metodos}, {"GET"})


if __name__ == "__main__":
    unittest.main()
