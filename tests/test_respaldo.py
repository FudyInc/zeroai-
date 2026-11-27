"""Respaldo diario cifrado: ida y vuelta real con openssl, poda y avisos de falla."""
import io
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import respaldo_diario as rd  # noqa: E402


def _descifrar(archivo: Path, clave: Path) -> tarfile.TarFile:
    r = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter",
                        str(rd.RESPALDO_PBKDF2_ITER), "-pass", f"file:{clave}",
                        "-in", str(archivo)], capture_output=True, check=True)
    return tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:gz")


class RespaldoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.raiz, self.destino = base / "repo", base / "nube"
        self.raiz.mkdir(); self.destino.mkdir()
        (self.raiz / "state.json").write_text('{"clients": {}}')
        (self.raiz / ".env").write_text("SECRETO=1\n")
        (self.raiz / ".runtime").mkdir()
        (self.raiz / ".runtime" / "x.json").write_text("{}")
        db = sqlite3.connect(self.raiz / "whatsapp-web-events.sqlite3")
        db.execute("create table e (v text)"); db.execute("insert into e values ('hola')")
        db.commit(); db.close()
        self.clave = base / "clave"
        self.clave.write_text("clave-de-prueba-larga")

    def tearDown(self):
        self.tmp.cleanup()

    def test_ida_y_vuelta_cifrada(self):
        r = rd.respaldar(self.raiz, self.destino, self.clave, extra=[])
        archivo = Path(r["archivo"])
        self.assertTrue(archivo.name.startswith("zeroai-") and archivo.name.endswith(".tar.gz.enc"))
        self.assertNotIn(b"SECRETO", archivo.read_bytes())          # va cifrado
        with _descifrar(archivo, self.clave) as tar:
            nombres = tar.getnames()
            self.assertIn("repo/state.json", nombres)
            self.assertIn("repo/.env", nombres)
            self.assertIn("repo/.runtime/x.json", nombres)
            datos = tar.extractfile("repo/whatsapp-web-events.sqlite3").read()
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as f:
            f.write(datos); f.flush()
            filas = sqlite3.connect(f.name).execute("select v from e").fetchall()
        self.assertEqual(filas, [("hola",)])                        # sqlite consistente

    def test_clave_equivocada_no_descifra(self):
        r = rd.respaldar(self.raiz, self.destino, self.clave, extra=[])
        otra = Path(self.tmp.name) / "otra"; otra.write_text("otra-clave")
        with self.assertRaises(subprocess.CalledProcessError):
            _descifrar(Path(r["archivo"]), otra)

    def test_poda_conserva_los_ultimos(self):
        for i in range(5):
            rd.respaldar(self.raiz, self.destino, self.clave, extra=[], retener=3,
                         ahora=1_700_000_000 + i * 86400)
        quedan = sorted(p.name for p in self.destino.glob("zeroai-*.tar.gz.enc"))
        self.assertEqual(len(quedan), 3)
        self.assertFalse(list(self.destino.glob(".*parcial")))

    def test_sin_clave_falla_y_no_deja_basura(self):
        with self.assertRaises(rd.RespaldoError):
            rd.respaldar(self.raiz, self.destino, Path(self.tmp.name) / "no-existe", extra=[])
        self.assertEqual(list(self.destino.iterdir()), [])

    def test_destino_inexistente_falla(self):
        with self.assertRaises(rd.RespaldoError):
            rd.respaldar(self.raiz, Path(self.tmp.name) / "nada", self.clave, extra=[])

    def test_main_avisa_al_dueno_si_falla(self):
        env = {"RESPALDO_DESTINO": str(Path(self.tmp.name) / "nada"),
               "RESPALDO_CLAVE_ARCHIVO": str(self.clave)}
        with mock.patch.dict(os.environ, env), \
                mock.patch("zero.alerts.notify_owner") as aviso:
            codigo = rd.main(["--raiz", str(self.raiz)])
        self.assertEqual(codigo, 1)
        aviso.assert_called_once()
        self.assertIn("FALLÓ", aviso.call_args[0][0])

    def test_main_ok(self):
        env = {"RESPALDO_DESTINO": str(self.destino), "RESPALDO_CLAVE_ARCHIVO": str(self.clave),
               "RESPALDO_EXTRA": ""}
        with mock.patch.dict(os.environ, env), mock.patch("zero.alerts.notify_owner") as aviso:
            self.assertEqual(rd.main(["--raiz", str(self.raiz)]), 0)
        aviso.assert_not_called()
        self.assertEqual(len(list(self.destino.glob("zeroai-*.tar.gz.enc"))), 1)


if __name__ == "__main__":
    unittest.main()
