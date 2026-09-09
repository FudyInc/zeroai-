"""El planificador lee `auditoria-criterio.json` con tres guardas, y no se cae con él.

Ese archivo es entrada EXTERNA: lo escribe AUDIT a mano desde otra rama, no lo genera
ningún script de este repo y —a diferencia de su hermano auditoria.json— no se
regenera solo. De ahí las tres guardas que se prueban acá:

  · vigencia — un arreglo "determinado" hace días puede estar hecho hoy. El único
    hallazgo real del archivo lo demuestra: pedía agregar `industry` a crm._FIELDS, y
    ese campo ya no existe. Sin tope, el primer efecto de leer el archivo habría sido
    encolar una tarea ya hecha.
  · consumo — lo enviado se marca, para que mañana no vuelva a entrar.
  · forma — un hallazgo incompleto se descarta POR ESCRITO, donde Diego lo ve.

Y sobre todo: nada de lo que traiga ese archivo puede tumbar al planificador.

Todo corre sobre JSON temporales. El archivo real no se lee ni se escribe nunca acá.

Run: python3 -m unittest tests.test_planificar_criterio -v
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import time
import unittest

_ruta = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "planificar.py"
_spec = importlib.util.spec_from_file_location("planificar", _ruta)
plan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plan)


def _hallazgo(**kw) -> dict:
    base = {"check": "contrato_vs_crm", "gravedad": "alta",
            "detalle": "algo medido está roto",
            "evidencia": "python3 -c \"print('lo reproduce')\""}
    base.update(kw)
    return base


class CriterioBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ruta = pathlib.Path(self._tmp.name) / "auditoria-criterio.json"
        self._original = plan.CRITERIO_PATH
        plan.CRITERIO_PATH = self.ruta
        self.addCleanup(setattr, plan, "CRITERIO_PATH", self._original)

    def _escribir(self, hallazgos, cuando=None, crudo=None):
        if crudo is not None:
            self.ruta.write_text(crudo, encoding="utf-8")
            return
        self.ruta.write_text(json.dumps(
            {"cuando": time.time() if cuando is None else cuando, "hallazgos": hallazgos},
            ensure_ascii=False), encoding="utf-8")


class Vigencia(CriterioBase):

    def test_un_hallazgo_reciente_entra(self):
        self._escribir([_hallazgo()])
        senales, descartadas, consumibles = plan.hallazgos_con_arreglo_determinado()
        self.assertEqual(len(senales), 1)
        self.assertIn("lo reproduce", senales[0])      # el comando viaja con la señal
        self.assertEqual(consumibles, [0])
        self.assertEqual(descartadas, [])

    def test_un_hallazgo_viejo_se_descarta_y_se_dice(self):
        """El caso real: el archivo lleva días ahí y el defecto ya se arregló."""
        viejo = time.time() - (plan.CRITERIO_VIGENCIA_DIAS + 3) * 86400
        self._escribir([_hallazgo()], cuando=viejo)
        senales, descartadas, consumibles = plan.hallazgos_con_arreglo_determinado()
        self.assertEqual((senales, consumibles), ([], []))
        self.assertIn("vencido", descartadas[0])
        self.assertIn("contrato_vs_crm", descartadas[0])

    def test_la_fecha_del_hallazgo_manda_sobre_la_del_informe(self):
        """Un hallazgo agregado hoy a un archivo viejo sigue siendo de hoy."""
        self._escribir([_hallazgo(cuando=time.time())],
                       cuando=time.time() - 30 * 86400)
        senales, _, _ = plan.hallazgos_con_arreglo_determinado()
        self.assertEqual(len(senales), 1)

    def test_una_fecha_ilegible_no_pasa_por_reciente(self):
        self._escribir([_hallazgo(cuando="ayer por la tarde")], cuando="tampoco")
        senales, descartadas, _ = plan.hallazgos_con_arreglo_determinado()
        self.assertEqual(senales, [])
        self.assertIn("sin fecha legible", descartadas[0])


class Forma(CriterioBase):

    def test_un_hallazgo_incompleto_se_descarta_por_escrito(self):
        """En silencio se leería igual que 'no había nada'."""
        self._escribir([{"check": "x", "gravedad": "alta"}])
        senales, descartadas, _ = plan.hallazgos_con_arreglo_determinado()
        self.assertEqual(senales, [])
        self.assertIn("sin detalle, evidencia", descartadas[0])

    def test_solo_entra_la_gravedad_alta(self):
        self._escribir([_hallazgo(gravedad="media")])
        senales, _, _ = plan.hallazgos_con_arreglo_determinado()
        self.assertEqual(senales, [])

    def test_el_workspace_y_los_archivos_viajan_con_la_señal(self):
        """Le dan al planificador con qué declarar el alcance de la tarea."""
        self._escribir([_hallazgo(extra={"workspace": "core", "archivos": ["zero/crm.py"]})])
        senales, _, _ = plan.hallazgos_con_arreglo_determinado()
        self.assertIn("workspace sugerido: core", senales[0])
        self.assertIn("zero/crm.py", senales[0])


class NadaPuedeTumbarAlPlanificador(CriterioBase):

    def test_json_invalido(self):
        self._escribir(None, crudo="{ esto no es json")
        senales, descartadas, _ = plan.hallazgos_con_arreglo_determinado()
        self.assertEqual(senales, [])
        self.assertIn("ilegible", descartadas[0])

    def test_json_que_no_es_un_objeto(self):
        self._escribir(None, crudo='["una lista"]')
        senales, descartadas, _ = plan.hallazgos_con_arreglo_determinado()
        self.assertEqual(senales, [])
        self.assertIn("se esperaba un objeto", descartadas[0])

    def test_archivo_ausente_no_es_un_problema(self):
        """Todavía no existe: no hay señal, y punto. No es algo que reportar."""
        self.assertFalse(self.ruta.exists())
        self.assertEqual(plan.hallazgos_con_arreglo_determinado(), ([], [], []))

    def test_hallazgos_que_no_son_objetos(self):
        self._escribir(["texto suelto", 42, _hallazgo()])
        senales, descartadas, _ = plan.hallazgos_con_arreglo_determinado()
        self.assertEqual(len(senales), 1)
        self.assertEqual(len(descartadas), 2)


class Consumo(CriterioBase):

    def test_lo_consumido_no_vuelve_a_entrar_manana(self):
        self._escribir([_hallazgo()])
        _, _, consumibles = plan.hallazgos_con_arreglo_determinado()
        plan.marcar_consumidos(consumibles)
        senales, descartadas, _ = plan.hallazgos_con_arreglo_determinado()
        self.assertEqual(senales, [])
        self.assertIn("ya consumido", descartadas[0])

    def test_marcar_conserva_el_resto_del_archivo(self):
        """El archivo lo mantiene AUDIT a mano: no se borra, no se mueve, y lo que
        no es la marca queda tal cual."""
        self._escribir([_hallazgo()])
        original = json.loads(self.ruta.read_text(encoding="utf-8"))
        plan.marcar_consumidos([0])
        ahora = json.loads(self.ruta.read_text(encoding="utf-8"))
        self.assertTrue(self.ruta.exists())
        self.assertEqual(ahora["cuando"], original["cuando"])
        marcado = ahora["hallazgos"][0]
        self.assertTrue(marcado.pop("consumido_en"))
        self.assertEqual(marcado, original["hallazgos"][0])

    def test_marcar_sin_indices_no_toca_nada(self):
        self._escribir([_hallazgo()])
        antes = self.ruta.read_text(encoding="utf-8")
        self.assertEqual(plan.marcar_consumidos([]), "")
        self.assertEqual(self.ruta.read_text(encoding="utf-8"), antes)

    def test_marcar_un_indice_que_no_existe_no_revienta(self):
        self._escribir([_hallazgo()])
        self.assertIn("0 hallazgo", plan.marcar_consumidos([7]))


if __name__ == "__main__":
    unittest.main()
