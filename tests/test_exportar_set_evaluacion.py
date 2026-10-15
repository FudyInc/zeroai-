"""Pruebas del exportador del set de evaluación (`scripts/exportar_set_evaluacion.py`).

Lo que se prueba es la anonimización, porque es lo único de este script que, si
falla, hace daño: un teléfono o un nombre real filtrado al repo no se puede
deshacer con un commit. El resto —contar casos, etiquetar— se prueba para que
el set sea reproducible, no porque sea delicado.
"""
import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "exportar_set_evaluacion", REPO / "scripts" / "exportar_set_evaluacion.py")
exportar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exportar)


class Anonimizacion(unittest.TestCase):
    def setUp(self):
        self.mapa = exportar.construir_mapa(
            {"56987654321@c.us": [], "56911112222@c.us": []}, ["Diego", "María Soto"])

    def test_el_telefono_conocido_recibe_un_numero_que_no_existe(self):
        fuera, _ = exportar.anonimizar("Mi número es 56987654321", self.mapa)
        self.assertNotIn("56987654321", fuera)
        self.assertIn("56900000", fuera)

    def test_un_telefono_desconocido_tambien_se_sustituye(self):
        fuera, _ = exportar.anonimizar("Llámame al +56 9 8765 4300", self.mapa)
        self.assertNotIn("87654300", fuera)

    def test_las_medidas_de_la_piscina_sobreviven(self):
        # El bug fácil: tratar «6 x 3» como teléfono y perder el caso de prueba
        # más importante del historial.
        fuera, _ = exportar.anonimizar("Mi piscina mide 6 x 3 metros", self.mapa)
        self.assertEqual(fuera, "Mi piscina mide 6 x 3 metros")

    def test_el_precio_sobrevive(self):
        fuera, _ = exportar.anonimizar("¿El borde sale $5.500 por unidad?", self.mapa)
        self.assertIn("5.500", fuera)

    def test_el_nombre_conocido_se_reemplaza_en_cualquier_caja(self):
        fuera, _ = exportar.anonimizar("Hola, habla diego", self.mapa)
        self.assertNotIn("diego", fuera.lower())
        self.assertIn("CLIENTE", fuera)

    def test_el_correo_se_reemplaza(self):
        fuera, _ = exportar.anonimizar("escríbeme a juan.perez@gmail.com", self.mapa)
        self.assertNotIn("juan.perez", fuera)
        self.assertIn("CORREO@ejemplo.cl", fuera)

    def test_la_direccion_se_reemplaza(self):
        fuera, _ = exportar.anonimizar("Despacho a Avenida Vicuña Mackenna 1234", self.mapa)
        self.assertNotIn("1234", fuera)
        self.assertIn("DIRECCION", fuera)

    def test_una_presentacion_con_nombre_nuevo_se_anonimiza(self):
        fuera, _ = exportar.anonimizar("Buenas, soy Rodrigo", self.mapa)
        self.assertNotIn("Rodrigo", fuera)

    def test_el_chat_id_conserva_su_forma(self):
        fuera, _ = exportar.anonimizar("chat 56987654321@c.us", self.mapa)
        self.assertNotIn("56987654321", fuera)
        self.assertIn("@c.us", fuera)

    def test_lo_dudoso_se_marca_en_vez_de_borrarse(self):
        # «Laja Española» es un producto, no una persona: tiene que sobrevivir,
        # pero quedar señalado para que una persona lo confirme.
        fuera, pendientes = exportar.anonimizar("Quiero Laja Española", self.mapa)
        self.assertIn("Laja", fuera)
        self.assertIn("Laja", pendientes)

    def test_un_token_en_el_historial_se_redacta(self):
        # Caso real encontrado al exportar: un mensaje traía una URL de GitHub
        # con `mcp_token=eyJ...`. Un secreto en el set es peor que no tenerlo.
        crudo = ("mira esto https://github.com/alguien/repo"
                 "?mcp_token=eyJwaWQiOjUwMTIzNDU2Nzg5.YWJjZGVmZ2hpams.c2lnbmF0dXJl")
        fuera, _ = exportar.anonimizar(crudo, self.mapa)
        self.assertNotIn("eyJ", fuera)
        self.assertNotIn("alguien", fuera)
        # Da igual si lo tapó la regla del token o la del enlace: lo que no
        # puede quedar es el secreto.
        self.assertRegex(fuera, r"SECRETO-REDACTADO|ENLACE-REDACTADO")

    def test_otros_nombres_de_parametro_sensibles_tambien(self):
        for param in ("api_key", "access_token", "session", "signature"):
            fuera, _ = exportar.anonimizar(f"https://x.cl/a?{param}=ABC123secreto", self.mapa)
            self.assertNotIn("ABC123secreto", fuera, param)

    def test_el_enlace_del_catalogo_sobrevive(self):
        # No todo enlace es un secreto: este es el que el agente envía a diario.
        fuera, _ = exportar.anonimizar("Catálogo https://wa.me/c/56964537891", self.mapa)
        self.assertIn("https://wa.me/c/", fuera)

    def test_una_url_cualquiera_se_redacta_entera(self):
        # Caso real: la ruta llevaba el usuario de GitHub de una persona.
        fuera, _ = exportar.anonimizar("mira https://github.com/unapersona/repo", self.mapa)
        self.assertNotIn("unapersona", fuera)
        self.assertIn("ENLACE-REDACTADO", fuera)

    def test_la_ubicacion_conserva_su_forma_y_pierde_las_coordenadas(self):
        crudo = "[location] https://www.google.com/maps?q=-33.456789,-70.123456"
        fuera, _ = exportar.anonimizar(crudo, self.mapa)
        self.assertIn("[location]", fuera)
        self.assertIn("google.com/maps", fuera)
        self.assertNotIn("-33.456789", fuera)

    def test_el_mismo_dato_da_siempre_el_mismo_seudonimo(self):
        uno, _ = exportar.anonimizar("56987654321", self.mapa)
        dos, _ = exportar.anonimizar("56987654321", self.mapa)
        self.assertEqual(uno, dos)

    def test_dos_contactos_distintos_no_se_confunden(self):
        uno, _ = exportar.anonimizar("56987654321", self.mapa)
        dos, _ = exportar.anonimizar("56911112222", self.mapa)
        self.assertNotEqual(uno, dos)


class Casos(unittest.TestCase):
    def _clientes(self):
        return {"losetaschile": {"conversations": {"56987654321@c.us": [
            {"role": "lead", "text": "Hola, soy Diego"},
            {"role": "agent", "text": "¡Buenas tardes! ¿En qué puedo ayudarte?"},
            {"role": "lead", "text": "Necesito pastelones"},
            {"role": "agent", "text": "¿Qué medidas necesitas?"},
            {"role": "lead", "text": "Mi piscina mide 6 x 3"},
        ]}}}

    def test_hay_un_caso_por_turno_del_cliente(self):
        casos, _ = exportar.construir_casos(self._clientes())
        self.assertEqual(len(casos), 3)
        self.assertEqual([c["mensaje"] for c in casos][1], "Necesito pastelones")

    def test_cada_caso_arrastra_el_historial_que_lo_precede(self):
        casos, _ = exportar.construir_casos(self._clientes())
        self.assertEqual(casos[0]["turnos_previos"], 0)
        self.assertEqual(casos[2]["turnos_previos"], 4)
        self.assertEqual(casos[2]["historial"][-1]["role"], "agent")

    def test_los_incidentes_conocidos_quedan_etiquetados(self):
        casos, _ = exportar.construir_casos(self._clientes())
        self.assertIn("pastelones-cantidad-inventada", casos[1]["etiquetas"])
        self.assertIn("medidas-piscina", casos[2]["etiquetas"])

    def test_ningun_caso_conserva_el_telefono_real(self):
        casos, _ = exportar.construir_casos(self._clientes())
        volcado = repr(casos)
        self.assertNotIn("56987654321", volcado)
        self.assertNotIn("Diego", volcado)

    def test_un_turno_vacio_no_genera_caso(self):
        clientes = {"x": {"conversations": {"56911112222@c.us": [
            {"role": "lead", "text": "   "}, {"role": "lead", "text": "hola"}]}}}
        casos, _ = exportar.construir_casos(clientes)
        self.assertEqual(len(casos), 1)


if __name__ == "__main__":
    unittest.main()
