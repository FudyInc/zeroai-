"""Respaldo diario cifrado: ida y vuelta real con openssl, verificación, clave,
poda y avisos de falla."""
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import respaldo_diario as rd  # noqa: E402

CLAVE = "k" * 48


def _descifrar(archivo: Path, clave: Path) -> tarfile.TarFile:
    r = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter",
                        str(rd.RESPALDO_PBKDF2_ITER), "-pass", f"file:{clave}",
                        "-in", str(archivo)], capture_output=True, check=True)
    return tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r:gz")


@unittest.skipUnless(shutil.which("openssl"), "requiere openssl en el PATH")
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
        os.symlink(base / "no-existe", self.raiz / ".runtime" / "roto.json")
        db = sqlite3.connect(self.raiz / "whatsapp-web-events.sqlite3")
        db.execute("create table e (v text)"); db.execute("insert into e values ('hola')")
        db.commit(); db.close()
        self.clave = base / "clave"
        self.clave.write_text(CLAVE + "\n")
        os.chmod(self.clave, 0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ida_y_vuelta_cifrada(self):
        r = rd.respaldar(self.raiz, self.destino, self.clave, extra=[])
        archivo = Path(r["archivo"])
        self.assertRegex(archivo.name, rd.NOMBRE_VALIDO)
        self.assertNotIn(b"SECRETO", archivo.read_bytes())          # va cifrado
        with _descifrar(archivo, self.clave) as tar:
            nombres = tar.getnames()
            self.assertIn("repo/state.json", nombres)
            self.assertIn("repo/.env", nombres)
            self.assertIn("repo/.runtime/x.json", nombres)
            self.assertNotIn("repo/.runtime/roto.json", nombres)    # symlink roto se omite
            datos = tar.extractfile("repo/whatsapp-web-events.sqlite3").read()
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as f:
            f.write(datos); f.flush()
            filas = sqlite3.connect(f.name).execute("select v from e").fetchall()
        self.assertEqual(filas, [("hola",)])                        # sqlite consistente

    def test_extra_incluye_carpetas_y_omite_lo_que_no_existe(self):
        extra = Path(self.tmp.name) / "fuera"
        (extra / "scripts").mkdir(parents=True)
        (extra / "scripts" / "sync.py").write_text("print(1)")
        r = rd.respaldar(self.raiz, self.destino, self.clave,
                         extra=[extra, Path(self.tmp.name) / "no-hay"])
        self.assertIn(str(extra), r["incluidos"])
        with _descifrar(Path(r["archivo"]), self.clave) as tar:
            self.assertTrue(any(n.endswith("fuera/scripts/sync.py") for n in tar.getnames()))

    def test_clave_equivocada_no_descifra(self):
        r = rd.respaldar(self.raiz, self.destino, self.clave, extra=[])
        otra = Path(self.tmp.name) / "otra"; otra.write_text("o" * 48)
        with self.assertRaises(subprocess.CalledProcessError):
            _descifrar(Path(r["archivo"]), otra)

    def test_clave_corta_o_vacia_se_rechaza(self):
        for contenido in ("", "corta\n", "\n" + CLAVE):
            self.clave.write_text(contenido)
            with self.assertRaises(rd.RespaldoError):
                rd.respaldar(self.raiz, self.destino, self.clave, extra=[])
        self.assertEqual(list(self.destino.iterdir()), [])

    def test_clave_legible_por_otros_se_rechaza(self):
        os.chmod(self.clave, 0o644)
        with self.assertRaises(rd.RespaldoError):
            rd.respaldar(self.raiz, self.destino, self.clave, extra=[])

    def test_verificacion_fallida_no_deja_respaldo_con_nombre_valido(self):
        with mock.patch.object(rd, "verificar", side_effect=rd.RespaldoError("corrupto")):
            with self.assertRaises(rd.RespaldoError):
                rd.respaldar(self.raiz, self.destino, self.clave, extra=[])
        self.assertEqual(list(self.destino.iterdir()), [])

    def test_verificar_detecta_un_archivo_danado(self):
        r = rd.respaldar(self.raiz, self.destino, self.clave, extra=[])
        archivo = Path(r["archivo"])
        datos = bytearray(archivo.read_bytes())
        archivo.write_bytes(bytes(datos[: len(datos) // 2]))       # truncado
        with self.assertRaises(rd.RespaldoError):
            rd.verificar(archivo, self.clave, esperados=1)

    def test_poda_conserva_los_ultimos_y_no_toca_lo_ajeno(self):
        ajeno = self.destino / "zeroai-notas.tar.gz.enc"; ajeno.write_text("mío")
        otro = self.destino / "fotos.zip"; otro.write_text("x")
        for i in range(5):
            rd.respaldar(self.raiz, self.destino, self.clave, extra=[], retener=3,
                         ahora=1_700_000_000 + i * 86400)
        propios = [p for p in self.destino.iterdir() if rd.NOMBRE_VALIDO.match(p.name)]
        self.assertEqual(len(propios), 3)
        self.assertTrue(ajeno.exists() and otro.exists())

    def test_poda_barre_parciales_huerfanos_viejos(self):
        viejo = self.destino / ".zeroai-20200101-0330.tar.gz.enc.parcial"
        viejo.write_text("x"); os.utime(viejo, (0, 0))
        nuevo = self.destino / ".zeroai-20991231-0330.tar.gz.enc.parcial"
        nuevo.write_text("x")
        rd.podar(self.destino, 14, time.time())
        self.assertFalse(viejo.exists())
        self.assertTrue(nuevo.exists())

    def test_sin_clave_falla_y_no_deja_basura(self):
        with self.assertRaises(rd.RespaldoError):
            rd.respaldar(self.raiz, self.destino, Path(self.tmp.name) / "no-existe", extra=[])
        self.assertEqual(list(self.destino.iterdir()), [])

    def test_destino_inexistente_falla(self):
        with self.assertRaises(rd.RespaldoError):
            rd.respaldar(self.raiz, Path(self.tmp.name) / "nada", self.clave, extra=[])

    def test_main_avisa_al_dueno_si_falla(self):
        env = {"RESPALDO_DESTINO": str(Path(self.tmp.name) / "nada"),
               "RESPALDO_CLAVE_ARCHIVO": str(self.clave), "WHATSAPP_WEB_EVENT_DB": ""}
        with mock.patch.dict(os.environ, env), \
                mock.patch("zero.alerts.notify_owner") as aviso:
            codigo = rd.main(["--raiz", str(self.raiz)])
        self.assertEqual(codigo, 1)
        aviso.assert_called_once()
        self.assertIn("FALLÓ", aviso.call_args[0][0])

    def test_main_ok_y_error_de_poda_avisa_sin_fallar(self):
        env = {"RESPALDO_DESTINO": str(self.destino), "RESPALDO_CLAVE_ARCHIVO": str(self.clave),
               "RESPALDO_EXTRA": "", "WHATSAPP_WEB_EVENT_DB": ""}
        with mock.patch.dict(os.environ, env), mock.patch("zero.alerts.notify_owner") as aviso, \
                mock.patch.object(rd, "podar", return_value=([], ["x: bloqueado"])):
            self.assertEqual(rd.main(["--raiz", str(self.raiz)]), 0)
        aviso.assert_called_once()
        self.assertIn("no se pudieron borrar", aviso.call_args[0][0])

    def test_main_respeta_whatsapp_web_event_db(self):
        otra = Path(self.tmp.name) / "eventos.sqlite3"
        db = sqlite3.connect(otra); db.execute("create table t (v)"); db.commit(); db.close()
        env = {"RESPALDO_DESTINO": str(self.destino), "RESPALDO_CLAVE_ARCHIVO": str(self.clave),
               "RESPALDO_EXTRA": "", "WHATSAPP_WEB_EVENT_DB": str(otra)}
        with mock.patch.dict(os.environ, env), mock.patch("zero.alerts.notify_owner"):
            self.assertEqual(rd.main(["--raiz", str(self.raiz)]), 0)
        archivo = next(p for p in self.destino.iterdir() if rd.NOMBRE_VALIDO.match(p.name))
        with _descifrar(archivo, self.clave) as tar:
            self.assertIn("repo/eventos.sqlite3", tar.getnames())

    def test_el_recien_creado_no_se_poda_aunque_haya_fechas_futuras(self):
        for d in ("20991230", "20991231"):
            (self.destino / f"zeroai-{d}-0330.tar.gz.enc").write_text("futuro")
        r = rd.respaldar(self.raiz, self.destino, self.clave, extra=[], retener=2)
        self.assertTrue(Path(r["archivo"]).exists())

    def test_conserva_permisos_y_fecha(self):
        extra = Path(self.tmp.name) / "fuera"; extra.mkdir()
        script = extra / "correr.sh"; script.write_text("echo hola")
        os.chmod(script, 0o755); os.utime(script, (1_600_000_000, 1_600_000_000))
        r = rd.respaldar(self.raiz, self.destino, self.clave, extra=[extra])
        with _descifrar(Path(r["archivo"]), self.clave) as tar:
            m = next(m for m in tar.getmembers() if m.name.endswith("correr.sh"))
        self.assertEqual(m.mode, 0o755)
        self.assertEqual(int(m.mtime), 1_600_000_000)

    def test_poda_no_lanza_si_no_puede_listar(self):
        borrados, errores = rd.podar(Path(self.tmp.name) / "no-existe", 3, time.time())
        self.assertEqual(borrados, [])
        self.assertTrue(errores)

    def test_bandeja_explicita_inexistente_falla(self):
        env = {"RESPALDO_DESTINO": str(self.destino), "RESPALDO_CLAVE_ARCHIVO": str(self.clave),
               "RESPALDO_EXTRA": "", "WHATSAPP_WEB_EVENT_DB": "/no/existe.sqlite3"}
        with mock.patch.dict(os.environ, env), mock.patch("zero.alerts.notify_owner") as aviso:
            self.assertEqual(rd.main(["--raiz", str(self.raiz)]), 1)
        self.assertIn("WHATSAPP_WEB_EVENT_DB", aviso.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
