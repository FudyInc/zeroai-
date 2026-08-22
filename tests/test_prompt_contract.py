"""Todo campo que el orquestador manda a un agente debe estar declarado en su prompt.

El bug que motiva este test es del 2026-08-21 (commit 7f74de8) y no rompe nada:
`orchestrator.reply_to_inbound` mandaba `data.knowledge` (la ficha de la empresa) a
CONCIERGE, pero `prompts/concierge.md` no mencionaba el campo en ninguna parte. El dato
viajaba completo y el modelo local (qwen2.5:14b) lo ignoraba, respondiendo genérico con
el detalle real disponible. Nada falla, no hay excepción, los tests pasan — el agente
simplemente contesta peor de lo que podría, y solo se nota leyendo respuestas a mano.

Es un desajuste detectable sin IA: los `TaskPayload(...)` de `zero/orchestrator.py`
declaran sus claves como literales, y los prompts son texto. Cruzar ambos es determinista.

Cuando este test falle, hay dos arreglos válidos:
  1. El prompt debe declarar el campo (lo normal) — documéntalo en su sección de entrada.
  2. El campo no debería viajar — sácalo del `data` en el orquestador. Si un dato no
     viaja, no puede filtrarse a la respuesta; es el patrón que se usó con el `icp`
     recortado de CONCIERGE.

Lo que este test NO comprueba: que el modelo *obedezca* el prompt. Ya sabemos que
declararlo no basta (ver el `icp` de CONCIERGE, que hubo que cortar en el mecanismo).
Esto solo garantiza que el prompt no ignore un dato que sí está llegando.
"""
import ast
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
ORCHESTRATOR = REPO / "zero" / "orchestrator.py"
PROMPTS = REPO / "prompts"


def _payloads_por_agente() -> dict:
    """{AGENTE: {claves de data}} leídas de los TaskPayload(...) del orquestador.

    Solo claves literales: un `data={**algo}` o una clave calculada se ignora en
    silencio, porque no se puede saber su nombre sin ejecutar el código. Prefiere
    quedarse corto a inventar un campo que no existe.
    """
    tree = ast.parse(ORCHESTRATOR.read_text(encoding="utf-8"))
    encontrados: dict = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "TaskPayload"):
            continue
        agente, claves = None, []
        for kw in node.keywords:
            if kw.arg == "agent" and isinstance(kw.value, ast.Constant):
                agente = kw.value.value
            elif kw.arg == "data" and isinstance(kw.value, ast.Dict):
                claves = [k.value for k in kw.value.keys
                          if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if agente:
            encontrados.setdefault(agente, set()).update(claves)
    return encontrados


class PromptDeclaraSuContexto(unittest.TestCase):

    def test_hay_payloads_que_revisar(self):
        """Red de seguridad del propio test: si el orquestador cambia de forma y el
        AST deja de encontrar payloads, este archivo pasaría en verde sin revisar
        nada — un test que no prueba nada es peor que no tenerlo."""
        payloads = _payloads_por_agente()
        self.assertGreaterEqual(len(payloads), 5,
                                f"solo se encontraron {len(payloads)} agentes en "
                                f"{ORCHESTRATOR.name}: ¿cambió la forma de TaskPayload?")

    def test_cada_agente_despachado_tiene_prompt(self):
        for agente in sorted(_payloads_por_agente()):
            with self.subTest(agente=agente):
                self.assertTrue((PROMPTS / f"{agente.lower()}.md").exists(),
                                f"{agente} se despacha pero no existe "
                                f"prompts/{agente.lower()}.md")

    def test_cada_campo_enviado_esta_declarado_en_el_prompt(self):
        for agente, claves in sorted(_payloads_por_agente().items()):
            prompt = PROMPTS / f"{agente.lower()}.md"
            if not prompt.exists():
                continue   # lo reporta el test de arriba; no se duplica el fallo
            texto = prompt.read_text(encoding="utf-8").lower()
            for clave in sorted(claves):
                with self.subTest(agente=agente, campo=clave):
                    # assertTrue y no assertRegex: al fallar, assertRegex vuelca el
                    # prompt COMPLETO (miles de caracteres) y entierra el mensaje útil.
                    # Un fallo ilegible es un fallo que se termina ignorando.
                    self.assertTrue(
                        re.search(rf"\b{re.escape(clave.lower())}\b", texto),
                        f"el orquestador manda `data.{clave}` a {agente} pero "
                        f"prompts/{agente.lower()}.md no lo menciona: el modelo va a "
                        f"ignorar el dato teniéndolo delante. Decláralo en el prompt, o "
                        f"deja de mandarlo desde el orquestador.")


if __name__ == "__main__":
    unittest.main()
