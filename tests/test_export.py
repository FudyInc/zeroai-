"""Tests de zero/export.py — contenido del CSV entregable (no solo el conteo).

test_core ya cuenta filas del happy path. Aquí se verifica el MAPEO real:
el mensaje de outreach se cruza por empresa, icp_reasons se une con ' | ',
las celdas None quedan vacías, y el caso sin leads escribe solo el header.
export es puro (data in, file out), así que se lee el archivo temporal.
"""
import csv
import os
import tempfile
import unittest

from zero import export


def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


class TestDeliverableToCsv(unittest.TestCase):
    def _run(self, deliverable):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "out.csv")
        n = export.deliverable_to_csv(deliverable, path)
        return n, _read(path)

    def test_header_y_conteo(self):
        n, rows = self._run({"qualified_leads": [{"company": "Acme"}], "outreach": []})
        self.assertEqual(n, 1)
        self.assertEqual(rows[0][:2], ["empresa", "contacto"])
        self.assertIn("mensaje", rows[0])
        self.assertIn("motivos_icp", rows[0])

    def test_cruza_outreach_por_empresa(self):
        deliverable = {
            "qualified_leads": [{"company": "Acme", "email": "a@acme.cl"}],
            "outreach": [{"company": "Acme", "subject": "Hola", "body": "Cuerpo"}],
        }
        _, rows = self._run(deliverable)
        fila = rows[1]
        self.assertIn("Hola", fila)     # asunto cruzado
        self.assertIn("Cuerpo", fila)   # mensaje cruzado

    def test_sin_outreach_deja_asunto_vacio(self):
        deliverable = {"qualified_leads": [{"company": "Acme"}], "outreach": []}
        _, rows = self._run(deliverable)
        # asunto y mensaje (últimas antes de motivos) quedan vacíos
        self.assertEqual(rows[1][-3], "")
        self.assertEqual(rows[1][-2], "")

    def test_icp_reasons_se_unen_con_pipe(self):
        deliverable = {
            "qualified_leads": [{"company": "Acme", "icp_reasons": ["rubro", "zona"]}],
            "outreach": [],
        }
        _, rows = self._run(deliverable)
        self.assertEqual(rows[1][-1], "rubro | zona")

    def test_none_se_vuelve_vacio(self):
        deliverable = {"qualified_leads": [{"company": "Acme", "email": None, "phone": None}],
                       "outreach": []}
        _, rows = self._run(deliverable)
        # ninguna celda debe ser el literal "None"
        self.assertNotIn("None", rows[1])

    def test_vacio_escribe_solo_header(self):
        n, rows = self._run({"qualified_leads": [], "outreach": []})
        self.assertEqual(n, 0)
        self.assertEqual(len(rows), 1)  # solo el header


class _FakeCRM:
    def __init__(self, leads):
        self._leads = leads

    def list(self, client):
        return self._leads


class TestCrmToCsv(unittest.TestCase):
    def test_incluye_etapa_y_actualizado(self):
        crm = _FakeCRM([{"company": "Acme", "stage": "won", "updated": "2026-07-01"}])
        d = tempfile.mkdtemp()
        path = os.path.join(d, "crm.csv")
        n = export.crm_to_csv(crm, "acme", path)
        rows = _read(path)
        self.assertEqual(n, 1)
        self.assertIn("etapa", rows[0])
        self.assertIn("actualizado", rows[0])
        self.assertIn("won", rows[1])
        self.assertIn("2026-07-01", rows[1])

    def test_vacio_solo_header(self):
        crm = _FakeCRM([])
        d = tempfile.mkdtemp()
        path = os.path.join(d, "crm.csv")
        n = export.crm_to_csv(crm, "acme", path)
        self.assertEqual(n, 0)
        self.assertEqual(len(_read(path)), 1)


if __name__ == "__main__":
    unittest.main()
