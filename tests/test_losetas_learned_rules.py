"""Reglas aprendidas de chats reales de PoolEdge (2026-11-11). Textos sintéticos.

A. «veo el catálogo y te respondo» → el agente espera.
B. Una pregunta nunca es una elección («¿aparte del Corrugado tienen otro?»).
C. «80 metros seguramente» son 80 m².
D. «ya», «yapo», «yapon», «sipo», «dale», «ok» son un sí.
E. Un número o una medida fuera de lista recibe las opciones válidas.
F. «volver al inicio» / «cargar de nuevo las medidas» reinicia el pedido o las medidas.
G. «ninguno», «no quiero nada» → cierre amable de una línea.
H. Reclamo, insulto o pedir una persona → pausa, aviso a Diego y acuse fijo.
I. «Losetas Chile» no sale en ningún texto: se dice PoolEdge.
"""
from unittest import mock

from zero.config import WHATSAPP_CLOSING_REPLY, WHATSAPP_HUMAN_REQUEST_ACK
from zero.losetas_polls import (CHILEAN_YES, PAVER_AREA_QUESTION, PAVER_MODEL_QUESTION,
                                POOL_SHAPE_QUESTION, PRODUCT_POLL_QUESTION, asks_question,
                                canonical_choice, customer_acknowledges, customer_closes,
                                customer_defers, paver_order_details, paver_size_reply,
                                restart_request, unsupported_paver_size)
from zero.orchestrator import _HUMAN_REQUEST_RE, _OLD_BRAND, _UPSET_RE

from tests.test_whatsapp_live_errors import _LiveChat


def _paver_history(area="80"):
    return [{"role": "agent", "text": PRODUCT_POLL_QUESTION},
            {"role": "lead", "text": "Pastelones"},
            {"role": "agent", "text": PAVER_AREA_QUESTION},
            {"role": "lead", "text": area},
            {"role": "agent", "text": f"Anoté {area} m². {PAVER_MODEL_QUESTION}"}]


class HedgedAreaTest(_LiveChat):  # C
    def test_hedged_areas_count_as_the_number(self):
        for text in ("80 metros seguramente", "unos 80", "80 mts aprox", "como 80 m2",
                     "creo que 80", "más o menos 80 metros"):
            history = [{"role": "agent", "text": PAVER_AREA_QUESTION},
                       {"role": "lead", "text": text}]
            self.assertEqual(paver_order_details("", history)["area_m2"], "80", text)

    def test_the_handler_notes_the_hedged_area(self):
        self.turns(("agent", PRODUCT_POLL_QUESTION), ("lead", "Pastelones"),
                   ("agent", PAVER_AREA_QUESTION))
        result = self.zero.converse_result(
            "losetaschile", "80 metros seguramente",
            history=self.memory.get_conversation("losetaschile", "56933333333"))
        self.assertTrue(result["reply"].startswith("Anoté 80 m²."), result["reply"])


class QuestionIsNotAChoiceTest(_LiveChat):  # B
    def test_asks_question(self):
        for text in ("¿aparte del Corrugado tienen otro?", "aparte del corrugado tienen otro",
                     "qué diferencia hay entre el deck y el liso", "tienen el gregoriano en gris",
                     "el liso sirve para piscina?"):
            self.assertTrue(asks_question(text), text)
        for text in ("Corrugado", "el 5", "80", "Liso por favor"):
            self.assertFalse(asks_question(text), text)

    def test_a_model_named_inside_a_question_is_not_chosen(self):
        history = _paver_history()
        history.append({"role": "lead", "text": "¿aparte del Corrugado tienen otro?"})
        details = paver_order_details("", history)
        self.assertEqual(details["area_m2"], "80")
        self.assertIsNone(details["model"])

    def test_a_plain_model_answer_is_still_chosen(self):
        history = _paver_history()
        history.append({"role": "lead", "text": "Corrugado"})
        self.assertIsNotNone(paver_order_details("", history)["model"])

    def test_the_handler_lets_the_model_answer_the_question(self):
        """La pregunta llega al modelo; el menú queda como recordatorio."""
        self.turns(*[(t["role"], t["text"]) for t in _paver_history()])
        with mock.patch.object(self.zero, "converse_result",
                               wraps=self.zero.converse_result) as spy:
            self.inbound("¿aparte del Corrugado tienen otro?")
        # La primera pasada repite el menú; la regla de re-pregunta abre el modelo.
        self.assertGreaterEqual(spy.call_count, 2)
        self.assertTrue(any(c.kwargs.get("open_menu") for c in spy.call_args_list))


class ChileanYesTest(_LiveChat):  # D
    def test_chilean_yes_answers_the_shape_menu(self):
        history = [{"role": "agent", "text": POOL_SHAPE_QUESTION}]
        for text in ("ya", "yapo", "yapon", "sipo", "dale", "ok", "Ya po"):
            self.assertIn(" ".join(text.casefold().split()), CHILEAN_YES | {"ya po"}, text)
            self.assertEqual(canonical_choice(text, history), "Sí, es rectangular", text)

    def test_chilean_yes_is_an_acknowledgement(self):
        for text in ("ya", "yapo", "yapon", "sipo", "ya po"):
            self.assertTrue(customer_acknowledges(text), text)


class InvalidOptionTest(_LiveChat):  # E
    def test_unsupported_paver_size(self):
        self.assertEqual(unsupported_paver_size("45x40"), "45×40")
        self.assertEqual(unsupported_paver_size("tienen de 60 x 60?"), "60×60")
        for text in ("40x40", "50 x 50", "4x8", "10x8", "80"):
            self.assertIsNone(unsupported_paver_size(text), text)

    def test_size_reply_lists_the_real_sizes(self):
        reply = paver_size_reply("45×40")
        self.assertIn("40×40", reply)
        self.assertIn("50×50", reply)
        self.assertIn("45×40", reply)

    def test_the_handler_answers_an_unsupported_size(self):
        self.turns(*[(t["role"], t["text"]) for t in _paver_history()])
        result = self.zero.converse_result(
            "losetaschile", "45x40",
            history=self.memory.get_conversation("losetaschile", "56933333333"))
        self.assertEqual(result["reply"], paver_size_reply("45×40"))


class RestartTest(_LiveChat):  # F
    def test_restart_request(self):
        self.assertEqual(restart_request("volver al inicio"), "order")
        self.assertEqual(restart_request("quiero empezar de nuevo"), "order")
        self.assertEqual(restart_request("cargar de nuevo las medidas"), "measures")
        self.assertIsNone(restart_request("80"))
        self.assertIsNone(restart_request("Corrugado"))

    def _ask(self, text):
        self.turns(*[(t["role"], t["text"]) for t in _paver_history()])
        return self.zero.converse_result(
            "losetaschile", text,
            history=self.memory.get_conversation("losetaschile", "56933333333"))

    def test_restart_measures_on_pastelones_asks_the_area_again(self):
        result = self._ask("cargar de nuevo las medidas")
        self.assertTrue(result["reply"].endswith(PAVER_AREA_QUESTION), result["reply"])
        # La nueva respuesta reemplaza a la vieja.
        history = _paver_history() + [
            {"role": "lead", "text": "cargar de nuevo las medidas"},
            {"role": "agent", "text": result["reply"]},
            {"role": "lead", "text": "40"}]
        self.assertEqual(paver_order_details("", history)["area_m2"], "40")

    def test_restart_order_goes_back_to_the_product_menu(self):
        result = self._ask("volver al inicio")
        self.assertIn(PRODUCT_POLL_QUESTION, result["reply"])
        self.assertEqual(result.get("customer_poll"), "product")


class PoliteCloseTest(_LiveChat):  # G
    def test_none_of_them_closes(self):
        for text in ("ninguno", "ninguno de esos", "ninguna me sirve", "no quiero nada",
                     "nada", "no me interesa", "ya no necesito"):
            self.assertTrue(customer_closes(text), text)

    def test_the_handler_closes_kindly(self):
        self.turns(*[(t["role"], t["text"]) for t in _paver_history()])
        result = self.zero.converse_result(
            "losetaschile", "ninguno",
            history=self.memory.get_conversation("losetaschile", "56933333333"))
        self.assertEqual(result["reply"], WHATSAPP_CLOSING_REPLY)


class DeferTest(_LiveChat):  # A
    def test_looking_at_the_catalog_waits(self):
        for text in ("veo el catálogo y te respondo", "lo reviso y te aviso",
                     "déjame verlo y te escribo"):
            self.assertTrue(customer_defers(text), text)


class PersonOrComplaintTest(_LiveChat):  # H
    def test_requests_for_a_person(self):
        for text in ("contáctame con un superior", "quiero hablar con alguien",
                     "pásame con el dueño", "contáctame con Diego", "me pueden llamar"):
            self.assertIsNotNone(_HUMAN_REQUEST_RE.search(text), text)
        for text in ("habla con el dueño del terreno", "no me sirve el 40x40",
                     "gracias, todo bien"):
            self.assertIsNone(_HUMAN_REQUEST_RE.search(text), text)

    def test_complaints_and_insults(self):
        for text in ("No me enviaste nunca la wea", "nunca llegó el catálogo?",
                     "nadie me responde", "pésima atención", "esto es una estafa"):
            self.assertIsNotNone(_UPSET_RE.search(text), text)
        for text in ("no me sirve el 40x40", "gracias, todo bien", "nunca he comprado"):
            self.assertIsNone(_UPSET_RE.search(text), text)

    def test_ack_names_diego(self):
        self.assertEqual(WHATSAPP_HUMAN_REQUEST_ACK,
                         "Le paso su mensaje a Diego, le responde él por aquí.")

    def test_a_complaint_pauses_and_alerts_the_owner(self):
        sent = []
        with mock.patch("zero.alerts.notify_owner",
                        side_effect=lambda text, **kw: sent.append((kw.get("kind"), text))
                        or {"status": "sent"}):
            result = self.inbound("No me enviaste nunca la wea")
        self.assertTrue(result["manual_review"])
        self.assertEqual(self.sent(), [WHATSAPP_HUMAN_REQUEST_ACK])
        self.assertEqual([k for k, _ in sent], ["whatsapp_person"])
        self.assertIn("pooledge", sent[0][1].casefold())
        self.assertIn("pausa", sent[0][1])
        self.assertIsNotNone(self.memory.get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))


class BrandTest(_LiveChat):  # I
    def test_old_brand_is_replaced(self):
        self.assertEqual(_OLD_BRAND.sub("PoolEdge", "Hola, somos Losetas Chile."),
                         "Hola, somos PoolEdge.")
        self.assertEqual(_OLD_BRAND.sub("PoolEdge", "LOSETASCHILE"), "PoolEdge")

    def test_a_model_reply_with_the_old_brand_goes_out_as_poolEdge(self):
        with mock.patch.object(self.zero, "converse_result", return_value={
                "reply": "Hola, te saluda Losetas Chile. ¿En qué te ayudo?",
                "intent": "general"}):
            self.inbound("hola")
        self.assertTrue(self.sent())
        self.assertNotIn("Losetas Chile", self.sent()[-1])
        self.assertIn("PoolEdge", self.sent()[-1])

    def test_internal_budget_headers_say_poolEdge(self):
        import inspect
        from zero import losetas_budget
        source = inspect.getsource(losetas_budget)
        self.assertIn("*PRESUPUESTO POOLEDGE · REVISIÓN INTERNA*", source)
        self.assertIn("*PEDIDO PASTELONES POOLEDGE · REVISIÓN INTERNA*", source)
        # Ningún encabezado en negrita lleva el nombre antiguo.
        self.assertNotRegex(source, r"\*[^*\n]*(?i:losetas)[^*\n]*\*")
