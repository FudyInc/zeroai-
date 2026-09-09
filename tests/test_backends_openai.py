"""El backend de OpenAI: que exista de verdad, y que no cueste plata por accidente.

Se agregó el 2026-09-08 porque la tarjeta "Inferencia" del mapa de arquitectura iba a
listar OpenAI, y esa tarjeta declara en su propio comentario que muestra "capabilities
confirmed in the repository". Anunciar un backend que no existe es exactamente el
defecto que se cerró ese mismo día en el resto del sistema.

Run: python3 -m unittest tests.test_backends_openai -v
"""
from __future__ import annotations

import unittest

from zero.backends import LocalBackend, OpenAIBackend


class EsElMismoTransporte(unittest.TestCase):
    """No hay código de red nuevo: Ollama y vLLM hablan el protocolo de OpenAI, así que
    `LocalBackend` ya lo implementaba. Heredar deja UNA sola ruta que mantener."""

    def test_hereda_de_localbackend(self):
        self.assertIsInstance(OpenAIBackend(api_key="sk-x"), LocalBackend)

    def test_apunta_a_openai_y_no_a_localhost(self):
        b = OpenAIBackend(api_key="sk-x")
        self.assertEqual(b.base_url, "https://api.openai.com/v1")

    def test_el_payload_es_el_mismo_contrato(self):
        """Si el payload divergiera, los agentes tendrían que saber en qué motor corren
        — que es justo lo que el diseño de backends intercambiables evita."""
        b = OpenAIBackend(api_key="sk-x", model="gpt-4o-mini")
        payload = b._build_payload("sistema", "usuario", 100)
        self.assertEqual(payload["model"], "gpt-4o-mini")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in payload["messages"]], ["system", "user"])


class NoCuestaPlataPorAccidente(unittest.TestCase):
    """Cada petición acá se cobra por token. Los errores tienen que salir ANTES de
    gastar, no a mitad de una corrida."""

    def test_sin_key_falla_al_construirlo(self):
        with self.assertRaises(ValueError):
            OpenAIBackend()

    def test_una_key_vacia_o_de_espacios_tampoco_sirve(self):
        """El modo de fallo que ya mordió en _agents_best: un env declarado pero sin
        valor. `OPENAI_API_KEY=` en un .env no puede parecer una key válida."""
        for valor in ("", " ", "\t"):
            with self.subTest(valor=repr(valor)):
                with self.assertRaises(ValueError):
                    OpenAIBackend(api_key=valor)

    def test_el_error_desarma_la_confusion_de_la_suscripcion(self):
        """Una suscripción de ChatGPT no da acceso a la API. Es la confusión más cara
        que puede tener alguien acá, y el error es donde se va a leer."""
        with self.assertRaises(ValueError) as ctx:
            OpenAIBackend()
        msg = str(ctx.exception)
        self.assertIn("platform.openai.com", msg)
        self.assertIn("ChatGPT", msg)

    def test_el_timeout_es_mucho_mas_corto_que_el_local(self):
        """En local se esperan minutos porque no cuesta nada. Acá cada segundo de espera
        es una petición pagada que sigue viva."""
        self.assertLess(OpenAIBackend(api_key="sk-x").timeout, LocalBackend().timeout)


if __name__ == "__main__":
    unittest.main()
