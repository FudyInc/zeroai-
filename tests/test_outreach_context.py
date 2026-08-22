"""Lo que OUTREACH recibe no le permite inventar hechos sobre el lead.

Encontrado en vivo (2026-08-22), redactando el primer correo real de ZeroAI a tres
leads: el modelo local escribió "he visto que atienden consultas frecuentemente a
través del WhatsApp" a las tres empresas. No vio nada — copió `icp.must_have`, que es
el criterio con el que BUSCAMOS leads ("atiende consultas seguido"), y lo afirmó como
observación sobre cada negocio.

Es el mismo patrón que el `icp.industry` de CONCIERGE del día anterior, y la misma
lección: pedírselo por prompt no basta con un modelo chico. Si el dato no viaja, no
puede filtrarse al mensaje.

La diferencia con CONCIERGE: allá el lead que escribe puede ser cualquiera, así que se
corta casi todo el ICP. Acá el lead SÍ fue elegido por el ICP, así que el segmento
(industry, regions, company_size, buyer_roles) sigue siendo cierto y se conserva —
recortar de más dejaría a OUTREACH sin con qué personalizar.
"""
import unittest

from zero.agents import build_agents
from zero.contracts import TaskPayload
from zero.memory import SessionMemory
from zero.orchestrator import Zero, _icp_para_outreach

ICP_COMPLETO = {
    "sells": "generación de leads B2B calificados",
    "industry": "retail y e-commerce",
    "regions": ["Chile"],
    "company_size": "pyme y mediana",
    "buyer_roles": ["dueño", "gerente comercial"],
    "must_have": ["presencia digital activa", "atiende consultas seguido"],
    "exclude": ["multinacionales grandes"],
}


class TestRecorteDelICP(unittest.TestCase):

    def test_los_criterios_de_filtro_no_pasan(self):
        recortado = _icp_para_outreach(ICP_COMPLETO)
        self.assertNotIn("must_have", recortado)
        self.assertNotIn("exclude", recortado)

    def test_el_segmento_si_pasa(self):
        """Recortar de más es el otro modo de falla: sin segmento, OUTREACH escribe
        un pitch genérico para todos."""
        recortado = _icp_para_outreach(ICP_COMPLETO)
        for campo in ("sells", "industry", "regions", "company_size", "buyer_roles"):
            with self.subTest(campo=campo):
                self.assertIn(campo, recortado)

    def test_icp_vacio_no_revienta(self):
        self.assertEqual(_icp_para_outreach({}), {})
        self.assertEqual(_icp_para_outreach(None), {})


class TestPipelineNoFiltraCriterios(unittest.TestCase):
    """La prueba que importa: el recorte tiene que estar en el camino real del
    pipeline, no solo en una función suelta que nadie llame."""

    def test_el_task_despachado_a_outreach_no_lleva_must_have(self):
        espiados = []

        class ZeroEspia(Zero):
            def dispatch(self, agent_name: str, task: TaskPayload):
                espiados.append((agent_name, task))
                return super().dispatch(agent_name, task)

        memory = SessionMemory(None)
        memory.set_client_icp("acme", ICP_COMPLETO)
        z = ZeroEspia(build_agents(mock=True), memory=memory)
        z.run_pipeline("acme", "GROWTH", "retail Chile", count=3)

        tasks = [t for name, t in espiados if name == "OUTREACH"]
        self.assertTrue(tasks, "el pipeline no despachó OUTREACH: el test no probó nada")
        for task in tasks:
            icp = task.data.get("icp") or {}
            self.assertNotIn("must_have", icp,
                             "los criterios de prospección llegaron a OUTREACH: el modelo "
                             "los va a afirmar como hechos sobre el lead")
            self.assertNotIn("exclude", icp)
            self.assertIn("sells", icp, "OUTREACH se quedó sin saber qué vende el cliente")


if __name__ == "__main__":
    unittest.main()
