"""Tests de zero/voice.py — TTS vía ElevenLabs (urllib).

Frontera con un servicio externo: se mockea urllib.request.urlopen y la env
ELEVENLABS_API_KEY. Se prueba la exigencia de credencial, el mapeo de voces,
el manejo de HTTPError y que speak escriba el MP3 con el body correcto —
sin red ni credenciales reales.
"""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from zero import voice


def _resp(data: bytes):
    """Context manager que imita la respuesta de urlopen."""
    m = mock.MagicMock()
    m.__enter__.return_value.read.return_value = data
    return m


def _http_error(code: int, msg: bytes = b"denegado"):
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(msg))


class TestKey(unittest.TestCase):
    def test_sin_key_lanza(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as cm:
                voice._key(None)
            self.assertIn("ELEVENLABS_API_KEY", str(cm.exception))

    def test_key_explicita_gana(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(voice._key("abc"), "abc")

    def test_key_desde_env(self):
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "envk"}, clear=True):
            self.assertEqual(voice._key(None), "envk")


class TestListVoices(unittest.TestCase):
    def test_mapea_id_y_nombre(self):
        payload = json.dumps({"voices": [
            {"voice_id": "v1", "name": "Fernanda"},
            {"voice_id": "v2", "name": "Otra"},
        ]}).encode()
        with mock.patch("zero.voice.urllib.request.urlopen", return_value=_resp(payload)):
            out = voice.list_voices(api_key="k")
            self.assertEqual(out, [("v1", "Fernanda"), ("v2", "Otra")])

    def test_sin_voces_da_lista_vacia(self):
        with mock.patch("zero.voice.urllib.request.urlopen", return_value=_resp(b'{}')):
            self.assertEqual(voice.list_voices(api_key="k"), [])

    def test_http_error_lanza_con_code(self):
        with mock.patch("zero.voice.urllib.request.urlopen", side_effect=_http_error(401)):
            with self.assertRaises(RuntimeError) as cm:
                voice.list_voices(api_key="k")
            self.assertIn("401", str(cm.exception))


class TestSpeak(unittest.TestCase):
    def test_escribe_mp3_y_devuelve_ruta(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "hola.mp3")
            with mock.patch("zero.voice.urllib.request.urlopen",
                            return_value=_resp(b"AUDIO")):
                ret = voice.speak("Hola", voice_id="v1", out=out, api_key="k")
            self.assertEqual(ret, out)
            with open(out, "rb") as fh:
                self.assertEqual(fh.read(), b"AUDIO")

    def test_body_incluye_texto_y_settings(self):
        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode())
            return _resp(b"AUDIO")

        with tempfile.TemporaryDirectory() as d, \
             mock.patch("zero.voice.urllib.request.urlopen", side_effect=fake_urlopen):
            voice.speak("Hola", voice_id="v1", out=os.path.join(d, "a.mp3"),
                        api_key="k", stability=0.3, similarity_boost=0.9)
        self.assertIn("v1", captured["url"])
        self.assertEqual(captured["body"]["text"], "Hola")
        self.assertEqual(captured["body"]["voice_settings"]["stability"], 0.3)
        self.assertEqual(captured["body"]["voice_settings"]["similarity_boost"], 0.9)
        self.assertEqual(captured["body"]["model_id"], voice.DEFAULT_MODEL)

    def test_http_error_lanza(self):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch("zero.voice.urllib.request.urlopen", side_effect=_http_error(422)):
            with self.assertRaises(RuntimeError) as cm:
                voice.speak("Hola", voice_id="v1", out=os.path.join(d, "a.mp3"), api_key="k")
            self.assertIn("422", str(cm.exception))


class TestMain(unittest.TestCase):
    def test_voices_lista_y_retorna_0(self):
        with mock.patch("zero.voice.list_voices", return_value=[("v1", "Fernanda")]):
            self.assertEqual(voice._main(["--voices"]), 0)

    def test_sin_args_suficientes_error(self):
        with self.assertRaises(SystemExit):
            voice._main(["--voice-id", "v1"])  # falta --text

    def test_speak_desde_cli(self):
        with mock.patch("zero.voice.speak", return_value="x.mp3") as sp:
            rc = voice._main(["--voice-id", "v1", "--text", "Hola", "--out", "x.mp3"])
            self.assertEqual(rc, 0)
            sp.assert_called_once()


if __name__ == "__main__":
    unittest.main()
