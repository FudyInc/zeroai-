"""Regresiones del catálogo visual de LosetasChile antes de enviar fotos reales."""
import unittest
from pathlib import Path
from unittest import mock

from zero.agents import build_agents
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.pool_border import visual_catalog_category

ROOT = Path(__file__).resolve().parents[1]
# El puente sirve las fotos desde aquí (whatsapp-web-bridge/index.js::catalogDir).
CATALOG_DIR = ROOT / "frontend/public/catalog/losetaschile"


class VisualCatalogTest(unittest.TestCase):
    def test_only_explicit_category_request_selects_catalog(self):
        self.assertEqual(visual_catalog_category("Envíame el catálogo de bordes"), "bordes")
        self.assertEqual(visual_catalog_category("Catálogo de pastelones"), "pastelones")
        for text in ("No me mandes el catálogo de bordes",
                     "¿Qué modelos de bordes tienen?",
                     "Envíame el catálogo de bordes y pastelones"):
            with self.subTest(text=text):
                self.assertIsNone(visual_catalog_category(text))

    def test_every_allowlisted_photo_exists_where_the_bridge_reads_it(self):
        from zero.whatsapp_web import _CATALOG_IMAGES

        self.assertTrue(_CATALOG_IMAGES)
        for filename in sorted(_CATALOG_IMAGES):
            with self.subTest(filename=filename):
                self.assertTrue((CATALOG_DIR / filename).is_file())

    def test_catalog_request_builds_document_without_model(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        zero = Zero(build_agents(mock=True), memory=memory)
        for text, category, title in (
                ("Envíame el catálogo de pastelones", "pastelones", "Catálogo Pastelones"),
                ("Envíame el catálogo de bordes", "bordes", "Catálogo Bordes de Piscina")):
            with self.subTest(text=text), mock.patch.object(zero, "dispatch") as dispatch:
                result = zero.converse_result(
                    "losetaschile", text, lead={"key": "test-lead"}, channel="whatsapp")
                dispatch.assert_not_called()
                self.assertEqual(result["intent"], "catalog")
                self.assertEqual(result["reply"], title)
                self.assertEqual(result["catalog_document"]["category"], category)
                self.assertIn("pricing", result["catalog_document"])


if __name__ == "__main__":
    unittest.main()
