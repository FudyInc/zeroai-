"""Regresiones del catálogo visual de LosetasChile antes de enviar fotos reales."""
import unittest
from pathlib import Path
from unittest import mock

from zero.agents import build_agents
from zero.config import LOSETASCHILE_VISUAL_CATALOGS
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.pool_border import visual_catalog_category


class VisualCatalogTest(unittest.TestCase):
    def test_only_explicit_category_request_selects_photos(self):
        self.assertEqual(visual_catalog_category("Envíame el catálogo de bordes"), "bordes")
        self.assertEqual(visual_catalog_category("Catálogo de pastelones"), "pastelones")
        for text in ("No me mandes el catálogo de bordes",
                     "¿Qué modelos de bordes tienen?",
                     "Envíame el catálogo de bordes y pastelones"):
            with self.subTest(text=text):
                self.assertIsNone(visual_catalog_category(text))

    def test_all_configured_photos_exist_in_send_allowlist(self):
        from zero.whatsapp_web import _CATALOG_IMAGES

        root = Path(__file__).resolve().parents[1] / "frontend/public/catalog/losetaschile"
        for category, photos in LOSETASCHILE_VISUAL_CATALOGS.items():
            self.assertTrue(photos, category)
            for filename, caption in photos:
                with self.subTest(category=category, filename=filename):
                    self.assertIn(filename, _CATALOG_IMAGES)
                    self.assertTrue((root / filename).is_file())
                    self.assertTrue(caption.strip())

    def test_catalog_draft_uses_photos_without_model(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        zero = Zero(build_agents(mock=True), memory=memory)
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "Envíame el catálogo de pastelones",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertEqual(result["intent"], "catalog")
        self.assertEqual(len(result["media_assets"]), len(LOSETASCHILE_VISUAL_CATALOGS["pastelones"]))
        expected = {filename for filename, _ in LOSETASCHILE_VISUAL_CATALOGS["pastelones"]}
        self.assertEqual({item["image"] for item in result["media_assets"]}, expected)


if __name__ == "__main__":
    unittest.main()
