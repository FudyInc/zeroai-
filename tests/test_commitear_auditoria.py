"""`audit/diaria` guarda UN commit por fecha, con el informe final de ese día.

Fallo medido, no supuesto. La guarda anti-commits-vacíos del script comparaba árboles
de git, y el informe lleva `cuando` (timestamp) más un `segundos` por check: el árbol
difiere siempre, así que la guarda no podía dispararse nunca. La rama lo muestra:

    197238b audit: informe del 2026-09-04 (0 hallazgos, 0 altos)
    6107408 audit: informe del 2026-09-04 (0 hallazgos, 0 altos)

Dos commits, mismo día, mismo mensaje; el único diff eran 20.3 → 20.5 segundos.

Todo esto corre sobre un repo git TEMPORAL creado por el test. Nunca sobre el repo
real: el script mueve una referencia, y una prueba que mueva `audit/diaria` de verdad
sería el mismo tipo de efecto irreversible que se está tratando de evitar. El script
acepta `AUDIT_REPO` justamente para esto.

Run: python3 -m unittest tests.test_commitear_auditoria -v
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "commitear-auditoria.sh"
HOY = subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()


def _informe(hallazgos=(), segundos=1.0, cuando=1000.0) -> dict:
    """Un informe con la forma real de auditar.py (`cuando`, `checks`, `hallazgos`)."""
    return {
        "cuando": cuando,
        "checks": [{"check": "tests", "hallazgos": len(hallazgos), "segundos": segundos}],
        "hallazgos": list(hallazgos),
    }


@unittest.skipUnless(shutil.which("git"), "sin git en el PATH")
class CommitPorFecha(unittest.TestCase):

    def setUp(self):
        self.repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "test@zeroai.cl")
        self._git("config", "user.name", "test")
        (self.repo / "README.md").write_text("repo de prueba\n", encoding="utf-8")
        # Igual que en el repo real: el informe está gitignorado (auditar.py lo
        # sobrescribe en cada corrida), y el script lo guarda fechado en la rama.
        (self.repo / ".gitignore").write_text("auditoria.json\n", encoding="utf-8")
        self._git("add", "README.md", ".gitignore")
        self._git("commit", "-qm", "inicial")

    # --- helpers -------------------------------------------------------------
    def _git(self, *args) -> str:
        r = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"git {' '.join(args)}: {r.stderr}")
        return r.stdout.strip()

    def _escribir(self, **kw) -> None:
        (self.repo / "auditoria.json").write_text(json.dumps(_informe(**kw)), encoding="utf-8")

    def _correr(self) -> str:
        env = dict(os.environ, AUDIT_REPO=str(self.repo))
        r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def _commits(self) -> int:
        return int(self._git("rev-list", "--count", "audit/diaria"))

    def _guardado(self) -> dict:
        return json.loads(self._git("show", f"audit/diaria:docs/auditoria/{HOY}.json"))

    # --- el fallo medido -----------------------------------------------------
    def test_correr_dos_veces_el_mismo_dia_no_duplica_el_commit(self):
        """LA prueba del arreglo: sin él, esto daba 2 commits para la misma fecha."""
        self._escribir()
        self._correr()
        self.assertEqual(self._commits(), 2)      # el inicial + el informe de hoy
        salida = self._correr()
        self.assertEqual(self._commits(), 2)
        self.assertIn("sin cambios", salida)

    def test_el_tiempo_de_ejecucion_no_cuenta_como_cambio(self):
        """Exactamente el diff de los dos commits reales: 20.3 → 20.5 segundos, y un
        `cuando` distinto. Eso no es información de salud."""
        self._escribir(segundos=20.3, cuando=1000.0)
        self._correr()
        antes = self._commits()
        self._escribir(segundos=20.5, cuando=9999.0)
        salida = self._correr()
        self.assertEqual(self._commits(), antes)
        self.assertIn("sin cambios", salida)

    # --- los tres casos ------------------------------------------------------
    def test_el_primer_informe_del_dia_crea_el_commit(self):
        self._escribir(hallazgos=[{"gravedad": "alta", "detalle": "x"}])
        salida = self._correr()
        self.assertIn("[nuevo]", salida)
        self.assertEqual(self._guardado()["hallazgos"][0]["detalle"], "x")
        self.assertIn(f"informe del {HOY} (1 hallazgos, 1 altos)",
                      self._git("log", "-1", "--format=%s", "audit/diaria"))

    def test_un_cambio_real_reemplaza_el_commit_de_hoy(self):
        """Queda el ÚLTIMO informe del día, y sigue habiendo un solo commit para la
        fecha — no una cadena de correcciones."""
        self._escribir()
        self._correr()
        antes = self._commits()
        self._escribir(hallazgos=[{"gravedad": "alta", "detalle": "algo se rompió"}])
        salida = self._correr()
        self.assertIn("[reemplazado]", salida)
        self.assertEqual(self._commits(), antes)          # reemplazo, no acumulación
        self.assertEqual(self._guardado()["hallazgos"][0]["detalle"], "algo se rompió")
        asuntos = self._git("log", "--format=%s", "audit/diaria").splitlines()
        self.assertEqual(len([a for a in asuntos if HOY in a]), 1)

    def test_un_dia_nuevo_no_pisa_el_informe_de_ayer(self):
        """El reemplazo es SOLO dentro de la misma fecha: el historial de salud se
        pierde entero si un día borra al anterior."""
        ayer = self.repo / "docs" / "auditoria" / "2026-01-01.json"
        ayer.parent.mkdir(parents=True, exist_ok=True)
        ayer.write_text(json.dumps(_informe()), encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "audit: informe del 2026-01-01 (0 hallazgos, 0 altos)")
        self._git("branch", "audit/diaria")
        self._git("reset", "-q", "--hard", "HEAD~1")       # main vuelve a su estado
        antes = self._commits()

        self._escribir()
        self._correr()
        self.assertEqual(self._commits(), antes + 1)
        self.assertTrue(self._git("cat-file", "-t",
                                  "audit/diaria:docs/auditoria/2026-01-01.json"))

    # --- lo que NO puede tocar ----------------------------------------------
    def test_no_cambia_de_rama_ni_ensucia_el_working_tree(self):
        """dia.sh corre tandas sobre este mismo working tree: un checkout le movería
        el suelo bajo los pies."""
        self._escribir()
        rama_antes = self._git("rev-parse", "--abbrev-ref", "HEAD")
        main_antes = self._git("rev-parse", "main")
        self._correr()
        self.assertEqual(self._git("rev-parse", "--abbrev-ref", "HEAD"), rama_antes)
        self.assertEqual(self._git("rev-parse", "main"), main_antes)   # main intacta
        self.assertEqual(self._git("status", "--porcelain"), "")

    def test_sin_informe_no_hace_nada(self):
        salida = self._correr()
        self.assertIn("sin auditoria.json", salida)
        # rev-parse devuelve 1 cuando la rama no existe: se mira el código, no la
        # salida, y por eso no pasa por el helper que exige éxito.
        existe = subprocess.run(["git", "rev-parse", "--verify", "--quiet",
                                 "refs/heads/audit/diaria"],
                                cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(existe.returncode, 1, "no debería haberse creado la rama")


if __name__ == "__main__":
    unittest.main()
