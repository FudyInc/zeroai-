"""La cola de trabajo no pierde tareas, no deja dos agentes en el mismo workspace, y
no permite que una tarea automática toque datos de producción.

Estas tres son las que sostienen todo el sistema autónomo: si la primera falla, el
trabajo se rehace; si la segunda falla, dos agentes se pisan los archivos sin enterarse;
si la tercera falla, un agente sin supervisión puede escribir en el CRM real o leer
credenciales.
"""
import os
import tempfile
import unittest
from unittest import mock

from zero import tasks


class ColaBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        ruta = os.path.join(self._tmp.name, "tareas.json")
        patch = mock.patch.dict(os.environ, {"TAREAS_PATH": ruta}, clear=False)
        patch.start()
        self.addCleanup(patch.stop)

    def _crear(self, ws="core", titulo="hacer algo", origen="diego", **kw):
        return tasks.crear(ws, titulo, "prompt detallado de la tarea", origen=origen, **kw)


class CrearYListar(ColaBase):

    def test_una_tarea_nace_pendiente(self):
        t = self._crear()
        self.assertEqual(t["estado"], tasks.PENDIENTE)
        self.assertEqual(t["intentos"], 0)
        self.assertEqual(len(tasks.listar()), 1)

    def test_sobrevive_al_proceso(self):
        """Lo único que la cola no puede hacer es perder trabajo."""
        t = self._crear()
        self.assertEqual(tasks.get(t["id"])["titulo"], "hacer algo")

    def test_workspace_desconocido_se_rechaza(self):
        with self.assertRaises(ValueError):
            tasks.crear("inventado", "x", "y")

    def test_titulo_o_prompt_vacio_se_rechaza(self):
        with self.assertRaises(ValueError):
            tasks.crear("core", "  ", "prompt")
        with self.assertRaises(ValueError):
            tasks.crear("core", "titulo", "   ")

    def test_lo_de_diego_va_antes_que_lo_deducido(self):
        """Cuando hay que recortar, lo que pidió una persona manda."""
        self._crear(titulo="deducida", origen="sistema")
        self._crear(titulo="pedida", origen="diego")
        self.assertEqual([t["titulo"] for t in tasks.listar()], ["pedida", "deducida"])


class AlcanceCerrado(ColaBase):
    """Una tarea automática no puede tocar datos de negocio ni credenciales."""

    def test_los_archivos_prohibidos_se_rechazan(self):
        for archivo in (".env", "crm.json", "state.json", "deploy/zero-backend.service",
                        "users.json"):
            with self.subTest(archivo=archivo):
                with self.assertRaises(ValueError):
                    self._crear(archivos=[archivo])

    def test_no_se_puede_salir_del_repo(self):
        for ruta in ("/etc/passwd", "../otro-repo/x.py", "zero/../../fuera.py"):
            with self.subTest(ruta=ruta):
                with self.assertRaises(ValueError):
                    self._crear(archivos=[ruta])

    def test_los_archivos_normales_pasan(self):
        t = self._crear(archivos=["zero/agents/outreach.py", "tests/test_core.py"])
        self.assertEqual(len(t["archivos"]), 2)


class UnAgentePorWorkspace(ColaBase):

    def test_tomar_marca_en_curso_y_cuenta_el_intento(self):
        self._crear()
        t = tasks.tomar("core")
        self.assertEqual(t["estado"], tasks.EN_CURSO)
        self.assertEqual(t["intentos"], 1)

    def test_no_entrega_una_segunda_tarea_del_mismo_workspace(self):
        """Dos agentes en el mismo worktree se pisan los archivos entre sí."""
        self._crear(titulo="una")
        self._crear(titulo="otra")
        self.assertIsNotNone(tasks.tomar("core"))
        self.assertIsNone(tasks.tomar("core"))

    def test_otro_workspace_sigue_disponible(self):
        self._crear(ws="core")
        self._crear(ws="dashboard")
        tasks.tomar("core")
        self.assertIsNotNone(tasks.tomar("dashboard"))

    def test_sin_tareas_devuelve_none(self):
        self.assertIsNone(tasks.tomar("landing"))


class VeredictoDelJuez(ColaBase):

    def test_aprobada_queda_aprobada(self):
        t = self._crear()
        tasks.tomar("core")
        tasks.a_revision(t["id"], rama="core", commit="abc123")
        final = tasks.juzgar(t["id"], aprobada=True, veredicto={"notas": "bien"})
        self.assertEqual(final["estado"], tasks.APROBADA)
        self.assertEqual(final["commit"], "abc123")

    def test_rechazada_vuelve_a_la_cola(self):
        t = self._crear()
        tasks.tomar("core")
        final = tasks.juzgar(t["id"], aprobada=False, veredicto={"notas": "rompe el contrato"})
        self.assertEqual(final["estado"], tasks.RECHAZADA)
        self.assertIsNotNone(tasks.tomar("core"))    # se puede reintentar

    def test_dos_rechazos_la_dejan_atascada(self):
        """Reintentar sin límite quema la cuota repitiendo el mismo error: un segundo
        rechazo casi nunca es mala suerte, es una tarea mal especificada."""
        t = self._crear()
        for _ in range(tasks.MAX_INTENTOS):
            tasks.tomar("core")
            tasks.juzgar(t["id"], aprobada=False, veredicto={"notas": "no"})
        self.assertEqual(tasks.get(t["id"])["estado"], tasks.ATASCADA)
        self.assertIsNone(tasks.tomar("core"))       # ya no se reintenta sola

    def test_el_veredicto_queda_guardado(self):
        """Una tarea rechazada sin su motivo se vuelve a intentar mañana igual."""
        t = self._crear()
        tasks.tomar("core")
        tasks.juzgar(t["id"], aprobada=False, veredicto={"riesgos": ["toca config"]})
        self.assertEqual(tasks.get(t["id"])["veredicto"]["riesgos"], ["toca config"])


class DevolverSinGastarIntento(ColaBase):
    """Un workspace ocupado o atrasado no es culpa de la tarea."""

    def test_devolver_no_gasta_intento(self):
        t = self._crear()
        tasks.tomar("core")
        self.assertEqual(tasks.get(t["id"])["intentos"], 1)
        tasks.devolver(t["id"], "workspace sucio")
        vuelta = tasks.get(t["id"])
        self.assertEqual(vuelta["estado"], tasks.PENDIENTE)
        self.assertEqual(vuelta["intentos"], 0)

    def test_dos_noches_saltada_no_la_dejan_atascada(self):
        """Sin esto, dos noches con el worktree sucio marcarían como fallida una tarea
        que nadie intentó nunca."""
        t = self._crear()
        for _ in range(tasks.MAX_INTENTOS + 2):
            tasks.tomar("core")
            tasks.devolver(t["id"], "workspace sucio")
        self.assertEqual(tasks.get(t["id"])["estado"], tasks.PENDIENTE)


class TareasColgadas(ColaBase):
    """Una tarea tomada por un proceso que murió bloquea su workspace para siempre."""

    def test_una_tarea_vieja_en_curso_se_libera(self):
        import time as _t
        t = self._crear()
        tasks.tomar("core")
        # Envejecer el último evento del historial, como si el proceso hubiera muerto.
        with mock.patch("time.time", return_value=_t.time() + 7200):
            liberadas = tasks.liberar_colgadas(minutos=60)
        self.assertEqual(len(liberadas), 1)
        self.assertEqual(tasks.get(t["id"])["estado"], tasks.PENDIENTE)

    def test_una_tarea_recien_tomada_no_se_toca(self):
        """Liberar demasiado pronto pondría a dos agentes en el mismo workspace."""
        self._crear()
        tasks.tomar("core")
        self.assertEqual(tasks.liberar_colgadas(minutos=60), [])

    def test_liberar_no_gasta_intento(self):
        import time as _t
        t = self._crear()
        tasks.tomar("core")
        with mock.patch("time.time", return_value=_t.time() + 7200):
            tasks.liberar_colgadas(minutos=60)
        self.assertEqual(tasks.get(t["id"])["intentos"], 0)


class ArchivoCorrupto(ColaBase):
    def test_no_se_sobreescribe_en_silencio(self):
        """Mismo criterio que crm.json: son tareas que alguien escribió."""
        with open(os.environ["TAREAS_PATH"], "w", encoding="utf-8") as fh:
            fh.write("{ esto no es json válido")
        with self.assertRaises(RuntimeError):
            tasks.listar()


class SinDuplicados(ColaBase):
    """La cola no puede volver a encolar trabajo que ya está abierto o hecho.

    Pasó de verdad: dos pares de duplicados exactos por título conviviendo en la cola,
    porque al planificador las tareas abiertas le llegan como *contexto* — una sugerencia
    a un modelo, no una regla. Cada duplicado se come una corrida del cupo diario para
    rehacer trabajo ya hecho.
    """

    def test_el_segundo_crear_devuelve_el_primero_y_no_encola(self):
        primera = self._crear(titulo="Agregar rubro del negocio a leads")
        segunda = self._crear(titulo="Agregar rubro del negocio a leads")
        self.assertEqual(segunda["id"], primera["id"])
        self.assertEqual(len(tasks.listar()), 1)

    def test_no_lanza_excepcion(self):
        """El planificador corre desatendido de noche: no puede caerse por esto."""
        self._crear(titulo="misma")
        self.assertIsNotNone(self._crear(titulo="misma"))

    def test_permitir_duplicado_fuerza_la_repeticion(self):
        primera = self._crear(titulo="misma")
        segunda = self._crear(titulo="misma", permitir_duplicado=True)
        self.assertNotEqual(segunda["id"], primera["id"])
        self.assertEqual(len(tasks.listar()), 2)

    def test_el_titulo_se_normaliza(self):
        """Mayúsculas, espacios de más y un punto final no hacen una tarea distinta."""
        self._crear(titulo="Unificar animaciones del dashboard")
        for variante in ("unificar animaciones del dashboard",
                         "  Unificar   animaciones del dashboard  ",
                         "Unificar animaciones del dashboard."):
            with self.subTest(variante=variante):
                self._crear(titulo=variante)
        self.assertEqual(len(tasks.listar()), 1)

    def test_el_mismo_titulo_en_otro_workspace_si_pasa(self):
        """Dos workspaces distintos son dos trabajos distintos."""
        self._crear(ws="core", titulo="subir la cobertura de tests")
        self._crear(ws="dashboard", titulo="subir la cobertura de tests")
        self.assertEqual(len(tasks.listar()), 2)

    def test_una_tarea_aprobada_tambien_bloquea(self):
        """Volver a encolar algo ya hecho es el caso caro: rehace trabajo entregado."""
        t = self._crear(titulo="ya hecha")
        tasks.tomar("core")
        tasks.juzgar(t["id"], aprobada=True, veredicto={"notas": "bien"})
        self._crear(titulo="ya hecha")
        self.assertEqual(len(tasks.listar()), 1)

    def test_una_cancelada_se_puede_volver_a_encolar(self):
        """Bajar una tarea a mano no es prohibirla para siempre."""
        t = self._crear(titulo="tal vez después")
        tasks.cancelar(t["id"], "por ahora no")
        nueva = self._crear(titulo="tal vez después")
        self.assertNotEqual(nueva["id"], t["id"])
        self.assertEqual(len(tasks.listar()), 2)

    def test_una_rechazada_se_puede_volver_a_encolar(self):
        """Que el juez la haya bajado es motivo legítimo para replantearla."""
        t = self._crear(titulo="replantearla")
        for _ in range(tasks.MAX_INTENTOS):
            tasks.tomar("core")
            tasks.juzgar(t["id"], aprobada=False, veredicto={"notas": "no"})
        self.assertEqual(tasks.get(t["id"])["estado"], tasks.ATASCADA)
        nueva = self._crear(titulo="replantearla")
        self.assertNotEqual(nueva["id"], t["id"])

    def test_duplicado_de_encuentra_la_existente(self):
        t = self._crear(titulo="Hacer   ALGO.")
        self.assertEqual(tasks.duplicado_de("core", "hacer algo")["id"], t["id"])
        self.assertIsNone(tasks.duplicado_de("dashboard", "hacer algo"))


class ListarDuplicados(ColaBase):
    """Ver qué se coló antes de la guardia. Solo lista: la limpieza la decide una persona."""

    def test_sin_duplicados_no_hay_grupos(self):
        self._crear(titulo="una")
        self._crear(titulo="otra")
        self.assertEqual(tasks.duplicados(), [])

    def test_agrupa_los_repetidos(self):
        a = self._crear(titulo="repetida", permitir_duplicado=True)
        b = self._crear(titulo="Repetida.", permitir_duplicado=True)
        self._crear(titulo="sola")
        grupos = tasks.duplicados()
        self.assertEqual(len(grupos), 1)
        self.assertEqual({t["id"] for t in grupos[0]}, {a["id"], b["id"]})

    def test_una_cancelada_no_cuenta_como_duplicado(self):
        a = self._crear(titulo="repetida", permitir_duplicado=True)
        b = self._crear(titulo="repetida", permitir_duplicado=True)
        tasks.cancelar(b["id"])
        self.assertEqual(tasks.duplicados(), [])
        self.assertEqual(tasks.duplicado_de("core", "repetida")["id"], a["id"])


class Resumen(ColaBase):
    def test_cuenta_por_estado_y_workspace(self):
        self._crear(ws="core")
        self._crear(ws="dashboard")
        tasks.tomar("core")
        r = tasks.resumen()
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["abiertas"], 2)
        self.assertEqual(r["por_estado"][tasks.EN_CURSO], 1)
        self.assertIn("dashboard", r["por_workspace"])


if __name__ == "__main__":
    unittest.main()
