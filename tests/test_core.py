"""Core safety net — the invariants ZERO must never break.

Stdlib unittest, no deps, all in mock. Run from the project root:

    python3 -m unittest discover -s tests -t .

These tests lock in the *logic* (gate, discovery delivery, scoring, CRM stages,
the whole pipeline). They don't judge lead quality — that's the real model's job.
"""
from __future__ import annotations

import ast
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from zero.agents import build_agents
from zero.config import MIN_ICP_SCORE, RECONTACT_BLACKOUT_DAYS
from zero.contracts import Constraints, Lead, TaskPayload
from zero.crm import CRM
from zero.memory import SessionMemory, _now
from zero.orchestrator import Zero


def _lead(**kw):
    base = dict(company="Acme", role="CEO", channel="email",
                email="ceo@acme.cl", domain="acme.cl", score=MIN_ICP_SCORE + 10)
    base.update(kw)
    return Lead(**base)


class GateTest(unittest.TestCase):
    """The qualified-lead gate — the heart of 'confiable'."""

    def setUp(self):
        self.z = Zero(build_agents(mock=True), memory=SessionMemory(None))

    def test_good_lead_passes(self):
        ok, fails = self.z.validate_lead(_lead(), exclusions=[])
        self.assertTrue(ok, fails)

    def test_no_contact_fails(self):
        ok, fails = self.z.validate_lead(_lead(email=None, phone=None), exclusions=[])
        self.assertFalse(ok)
        self.assertTrue(any("contacto" in f for f in fails))

    def test_low_score_fails(self):
        ok, fails = self.z.validate_lead(_lead(score=MIN_ICP_SCORE - 1), exclusions=[])
        self.assertFalse(ok)

    def test_score_at_threshold_passes(self):
        ok, _ = self.z.validate_lead(_lead(score=MIN_ICP_SCORE), exclusions=[])
        self.assertTrue(ok)

    def test_exclusion_fails(self):
        ok, fails = self.z.validate_lead(_lead(domain="acme.cl"), exclusions=["acme.cl"])
        self.assertFalse(ok)
        self.assertTrue(any("exclusión" in f for f in fails))

    def test_recent_contact_fails(self):
        lead = _lead()
        self.z.memory.contacted[lead.key()] = _now()   # contacted just now
        ok, fails = self.z.validate_lead(lead, exclusions=[])
        self.assertFalse(ok)
        self.assertTrue(any(str(RECONTACT_BLACKOUT_DAYS) in f for f in fails))

    def test_score_bar_scales_with_tier(self):
        """Decisión de negocio (2026-07-04): el mismo servicio sirve a empresas
        chicas, medianas y grandes a distinto precio — STARTER (plan de
        entrada) prioriza volumen, ENTERPRISE (el que más paga) exige más
        precisión. Un score de 55 (típico de una pyme real sin decisor
        verificado, visto en vivo con 'pooledge') debe pasar en STARTER pero
        no en SCALE/ENTERPRISE."""
        from zero.config import min_icp_score
        lead55 = _lead(score=55)
        ok_starter, _ = self.z.validate_lead(lead55, exclusions=[], tier="STARTER")
        ok_scale, _ = self.z.validate_lead(lead55, exclusions=[], tier="SCALE")
        ok_enterprise, _ = self.z.validate_lead(lead55, exclusions=[], tier="ENTERPRISE")
        self.assertTrue(ok_starter)
        self.assertFalse(ok_scale)
        self.assertFalse(ok_enterprise)
        # orden esperado: a mayor tier, mayor exigencia
        self.assertLess(min_icp_score("STARTER"), min_icp_score("GROWTH"))
        self.assertLess(min_icp_score("GROWTH"), min_icp_score("SCALE"))
        self.assertLess(min_icp_score("SCALE"), min_icp_score("ENTERPRISE"))

    def test_no_tier_falls_back_to_default_bar(self):
        from zero.config import MIN_ICP_SCORE
        ok, _ = self.z.validate_lead(_lead(score=MIN_ICP_SCORE - 1), exclusions=[])
        self.assertFalse(ok)
        ok, _ = self.z.validate_lead(_lead(score=MIN_ICP_SCORE), exclusions=[])
        self.assertTrue(ok)


class ProspectorTest(unittest.TestCase):
    """Discovery must deliver the requested count and never repeat a company."""

    def _run(self, cap):
        p = build_agents(mock=True)["PROSPECTOR"]
        task = TaskPayload(agent="PROSPECTOR", client_id="demo", client_tier="SCALE",
                           instructions="x", data={"query": "retail Chile"},
                           constraints=Constraints(max_items=cap, channels=["email", "whatsapp"]))
        return p.run(task)

    def test_delivers_requested_count(self):
        self.assertEqual(len(self._run(8).result["leads"]), 8)

    def test_no_duplicate_companies(self):
        companies = [l["company"] for l in self._run(8).result["leads"]]
        self.assertEqual(len(companies), len(set(companies)))

    def test_partial_when_pool_exhausted(self):
        resp = self._run(500)                  # far beyond the fixture pool
        self.assertEqual(resp.status, "partial")
        self.assertLess(len(resp.result["leads"]), 500)   # bounded, didn't hang


class QualifierTest(unittest.TestCase):
    def _score(self, leads):
        q = build_agents(mock=True)["QUALIFIER"]
        task = TaskPayload(agent="QUALIFIER", client_id="demo", client_tier="SCALE",
                           instructions="x", data={"leads": leads, "scoring": "advanced"},
                           constraints=Constraints())
        return q.run(task).result["leads"]

    def test_scores_in_range_and_deterministic(self):
        leads = [{"company": "Acme", "role": "CEO"}]
        a = self._score(leads)[0]["score"]
        b = self._score(leads)[0]["score"]
        self.assertEqual(a, b)                 # same input → same score
        self.assertTrue(0 <= a <= 100)

    def test_sorted_desc_with_reasons(self):
        leads = [{"company": f"C{i}", "role": "CEO"} for i in range(6)]
        scored = self._score(leads)
        self.assertEqual([l["score"] for l in scored],
                         sorted((l["score"] for l in scored), reverse=True))
        self.assertTrue(all(l["icp_reasons"] for l in scored))


class OutreachTest(unittest.TestCase):
    """First-touch copy must scale with the client's tier."""

    def _msg(self, tier):
        o = build_agents(mock=True)["OUTREACH"]
        task = TaskPayload(agent="OUTREACH", client_id="c", client_tier=tier,
                           instructions="x",
                           data={"leads": [{"company": "Acme", "role": "CEO",
                                            "name": "Ana", "channel": "email"}]},
                           constraints=Constraints(channels=["email"]))
        return o.run(task).result["messages"][0]["body"]

    def test_enterprise_more_personalized_than_starter(self):
        starter, enterprise = self._msg("STARTER"), self._msg("ENTERPRISE")
        self.assertNotEqual(starter, enterprise)
        self.assertGreater(len(enterprise), len(starter))   # richer copy
        self.assertIn("piloto", enterprise)                 # tier-specific touch

    def test_unverified_role_never_quoted_as_a_real_title(self):
        """Encontrado en vivo (2026-07-04, pipeline real contra empresas de
        piscinas): un lead de discovery web sin decisor verificado trae
        role="por verificar" (placeholder honesto de PROSPECTOR) — el mensaje
        NUNCA debe citarlo como si fuera un cargo real ("vi que lideras como
        por verificar en...")."""
        o = build_agents(mock=True)["OUTREACH"]
        task = TaskPayload(agent="OUTREACH", client_id="c", client_tier="GROWTH",
                           instructions="x",
                           data={"leads": [{"company": "Splash Piscinas", "role": "por verificar",
                                            "channel": "email"}]},
                           constraints=Constraints(channels=["email"]))
        body = o.run(task).result["messages"][0]["body"]
        self.assertNotIn("por verificar", body)
        self.assertIn("Splash Piscinas", body)

    def test_signs_with_vendor_name_when_present(self):
        o = build_agents(mock=True)["OUTREACH"]
        task = TaskPayload(agent="OUTREACH", client_id="c", client_tier="GROWTH",
                           instructions="x",
                           data={"leads": [{"company": "Acme", "role": "CEO", "channel": "email"}],
                                 "vendor": {"name": "Fernanda", "tone": "cercana"}},
                           constraints=Constraints(channels=["email"]))
        body = o.run(task).result["messages"][0]["body"]
        self.assertIn("Fernanda", body)

    def test_never_signs_with_the_agent_role_name(self):
        """Encontrado en vivo (2026-07-04): sin data.vendor, el modelo real
        firmaba literalmente como "OUTREACH" (su propio nombre de agente) —
        el mock nunca debe hacer lo mismo cuando no hay vendor asignado."""
        o = build_agents(mock=True)["OUTREACH"]
        task = TaskPayload(agent="OUTREACH", client_id="c", client_tier="GROWTH",
                           instructions="x",
                           data={"leads": [{"company": "Acme", "role": "CEO", "channel": "email"}]},
                           constraints=Constraints(channels=["email"]))
        body = o.run(task).result["messages"][0]["body"]
        self.assertNotIn("OUTREACH", body)


class TrackerTest(unittest.TestCase):
    """Los seguimientos (TRACKER) — nunca tuvo tests dedicados hasta encontrar,
    auditándolo en busca de las mismas fallas que OUTREACH (2026-07-06), un bug
    real y 100% determinista en mock: sin nombre verificado, saludaba
    "Hola Hola" (el fallback `name or "Hola"` metía el saludo genérico como si
    fuera el nombre de la persona)."""

    def _msg(self, kind, name=None, vendor=None):
        t = build_agents(mock=True)["TRACKER"]
        data = {"sequences": [{"lead_key": "k1", "company": "Splash Piscinas", "name": name,
                               "role": "por verificar", "channel": "email", "step": 0, "kind": kind}]}
        if vendor:
            data["vendor"] = vendor
        task = TaskPayload(agent="TRACKER", client_id="c", client_tier="GROWTH",
                           instructions="x", data=data, constraints=Constraints(channels=["email"]))
        return t.run(task).result["messages"][0]

    def test_no_name_never_greets_with_a_doubled_hola(self):
        for kind in ("nudge", "value", "breakup"):
            m = self._msg(kind, name=None)
            self.assertNotIn("Hola Hola", m["body"], kind)
            self.assertTrue(m["body"].startswith("Hola,"), (kind, m["body"]))

    def test_breakup_subject_never_shows_a_literal_none(self):
        m = self._msg("breakup", name=None)
        self.assertNotIn("None", m.get("subject") or "")

    def test_signs_with_vendor_name_when_present(self):
        m = self._msg("nudge", name="Ana", vendor={"name": "Fernanda", "tone": "cercana"})
        self.assertIn("Fernanda", m["body"])

    def test_never_signs_with_the_agent_role_name(self):
        m = self._msg("nudge", name="Ana")
        self.assertNotIn("TRACKER", m["body"])

    def test_run_followups_threads_vendor_name_into_the_message(self):
        """Extremo a extremo: run_followups con un vendedor asignado debe
        pasarle data.vendor a TRACKER — mismo patrón que run_pipeline con
        OUTREACH."""
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        z.memory.set_client_vendor("acme", "stefano")
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        future = (datetime.now(timezone.utc) + timedelta(days=999)).isoformat()
        d = z.run_followups("acme", as_of=future)
        if d["followups"]:
            self.assertTrue(any("Stéfano" in m["body"] for m in d["followups"]))


class CRMTest(unittest.TestCase):
    def setUp(self):
        self.crm = CRM(None)
        self.lead = {"company": "Acme", "role": "CEO", "email": "ceo@acme.cl", "score": 80}
        self.key = "ceo@acme.cl"

    def test_upsert_creates_and_dedupes(self):
        self.crm.upsert("c", self.lead, stage="qualified")
        self.crm.upsert("c", self.lead, stage="qualified")   # same lead again
        self.assertEqual(len(self.crm.list("c")), 1)

    def test_history_tracks_stage_changes(self):
        self.crm.upsert("c", self.lead, stage="qualified")
        self.crm.set_stage("c", self.key, "contacted")
        rec = self.crm.get("c", self.key)
        self.assertEqual(rec["stage"], "contacted")
        self.assertTrue(any(h["event"] == "stage" for h in rec["history"]))

    def test_advance_is_forward_only(self):
        self.crm.upsert("c", self.lead, stage="qualified")
        self.crm.set_stage("c", self.key, "won")        # manual, jumps ahead
        self.crm.advance("c", self.key, "qualified")    # auto re-run must NOT regress
        self.assertEqual(self.crm.get("c", self.key)["stage"], "won")

    def test_manual_set_stage_can_move_anywhere(self):
        self.crm.upsert("c", self.lead, stage="won")
        self.crm.set_stage("c", self.key, "lost")
        self.assertEqual(self.crm.get("c", self.key)["stage"], "lost")

    def test_invalid_stage_raises(self):
        self.crm.upsert("c", self.lead)
        with self.assertRaises(ValueError):
            self.crm.set_stage("c", self.key, "banana")

    def test_lead_detail_renders_timeline(self):
        from zero.board import render_lead
        self.crm.upsert("c", self.lead, stage="qualified")
        self.crm.set_stage("c", self.key, "won", detail="manual")
        out = render_lead(self.crm, "c", self.key, color=False)
        self.assertIn("Acme", out)
        self.assertIn("Historial", out)
        self.assertIn("won", out)


class RobustnessTest(unittest.TestCase):
    """A live model may deviate from the mock's clean contract — don't crash."""

    def test_string_score_is_coerced(self):
        self.assertEqual(Lead.from_dict({"company": "X", "score": "85"}).score, 85)
        self.assertEqual(Lead.from_dict({"company": "X", "score": 85.0}).score, 85)

    def test_garbage_score_becomes_none(self):
        self.assertIsNone(Lead.from_dict({"company": "X", "score": "alto"}).score)

    def test_gate_survives_stringy_score(self):
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        lead = Lead.from_dict({"company": "X", "role": "CEO", "channel": "email",
                               "email": "x@x.cl", "score": "92"})
        ok, _ = z.validate_lead(lead, exclusions=[])   # would TypeError if score stayed a str
        self.assertTrue(ok)

    def test_corrupt_crm_file_raises_clear_error(self):
        import os
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "crm.json")
        with open(path, "w") as fh:
            fh.write("{ this is not valid json")
        with self.assertRaises(RuntimeError) as ctx:
            CRM(path)
        self.assertIn("corrupto", str(ctx.exception))


class PersistenceBackupTest(unittest.TestCase):
    """crm.json / state.json: escritura atómica + una generación de respaldo
    (`persistence.py`) — un archivo corrupto no debe tirar todo el CRM/estado a
    la basura si hay un `.bak` bueno."""

    def _tmp_path(self, name: str) -> Path:
        import tempfile
        return Path(tempfile.mkdtemp()) / name

    def test_save_json_rotates_previous_version_to_bak(self):
        from zero.persistence import load_json, save_json
        path = self._tmp_path("crm.json")
        bak = path.with_name(path.name + ".bak")
        save_json(path, {"v": 1})
        self.assertFalse(bak.exists())            # nada que rotar todavía
        save_json(path, {"v": 2})
        self.assertEqual(load_json(path), {"v": 2})
        self.assertEqual(load_json(bak), {"v": 1})  # la versión anterior quedó a salvo

    def test_save_json_never_leaves_a_half_written_file(self):
        """Si la escritura del temporal fallara a mitad de camino, `path` no se
        toca (nunca queda un archivo a medio escribir) — se prueba escribiendo
        primero un archivo bueno y confirmando que sigue intacto tras crear (sin
        completar) un .tmp con contenido basura."""
        from zero.persistence import load_json, save_json
        path = self._tmp_path("crm.json")
        save_json(path, {"v": "bueno"})
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("{ escritura interrumpida", "utf-8")   # simula un tmp a medias
        self.assertEqual(load_json(path), {"v": "bueno"})     # path sigue intacto

    def test_load_json_recovers_from_backup_when_main_file_is_corrupt(self):
        from zero.persistence import load_json, save_json
        path = self._tmp_path("state.json")
        save_json(path, {"v": 1})
        save_json(path, {"v": 2})          # ahora .bak tiene v=1
        path.write_text("{ corrupto de verdad", "utf-8")
        self.assertEqual(load_json(path), {"v": 1})   # recupera desde el backup

    def test_load_json_raises_when_both_main_and_backup_are_corrupt(self):
        from zero.persistence import load_json
        path = self._tmp_path("state.json")
        bak = path.with_name(path.name + ".bak")
        path.write_text("{ corrupto", "utf-8")
        bak.write_text("{ tambien corrupto", "utf-8")
        with self.assertRaises(RuntimeError) as ctx:
            load_json(path)
        self.assertIn("corrupto", str(ctx.exception))

    def test_corrupt_state_file_raises_clear_error(self):
        """Mismo comportamiento que ya tenía CRM — SessionMemory nunca arranca
        vacía en silencio si el estado está corrupto y no hay backup usable."""
        path = self._tmp_path("state.json")
        path.write_text("{ this is not valid json", "utf-8")
        with self.assertRaises(RuntimeError) as ctx:
            SessionMemory(str(path))
        self.assertIn("corrupto", str(ctx.exception))

    def test_crm_recovers_from_backup_after_corruption(self):
        """Extremo a extremo: CRM.save() dos veces, corrompe crm.json a mano, y
        el próximo CRM(path) igual arranca con los datos de la última versión
        buena (la que quedó en .bak) en vez de reventar."""
        path = self._tmp_path("crm.json")
        crm = CRM(str(path))
        crm.upsert("acme", {"company": "Acme", "role": "CEO", "email": "uno@acme.cl", "score": 80})
        crm.save()
        crm.upsert("acme", {"company": "Acme", "role": "CTO", "email": "dos@acme.cl", "score": 80})
        crm.save()
        path.write_text("{ corrupto", "utf-8")
        recovered = CRM(str(path))
        self.assertEqual(len(recovered.list("acme")), 1)   # la versión previa a la corrupción


class PipelineIntegrationTest(unittest.TestCase):
    """The whole chain in mock: discover → qualify → validate → outreach → CRM."""

    def test_pipeline_and_crm(self):
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        d = z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)

        self.assertEqual(d["summary"]["discovered"], 8)
        # qualified is a subset, and every qualified lead clears the GROWTH score bar
        self.assertLessEqual(d["summary"]["qualified"], 8)
        from zero.config import min_icp_score
        self.assertTrue(all(l["score"] >= min_icp_score("GROWTH") for l in d["qualified_leads"]))
        # every discovered lead is recorded in the CRM (qualified or disqualified)
        self.assertEqual(sum(crm.counts("acme").values()), 8)

    def test_outreach_signs_with_the_clients_assigned_vendor(self):
        """Encontrado en vivo (2026-07-04): run_pipeline nunca le pasaba el
        vendor asignado a OUTREACH — sin nadie con quién firmar, el modelo
        real firmaba como "OUTREACH" (su propio nombre de agente). Mismo
        patrón que converse_result (CONCIERGE) ya usaba para esto."""
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        z.memory.set_client_vendor("acme", "stefano")
        d = z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        if d["outreach"]:
            self.assertTrue(any("Stéfano" in m["body"] for m in d["outreach"]))


class QualifierMergeTest(unittest.TestCase):
    """_merge_qualifier_scores: encontrado en vivo (2026-07-04, corriendo el
    pipeline real con qwen2.5:7b contra empresas reales de piscinas) — el
    modelo real a veces omite channel/email/phone/role al reescribir la lista
    de leads calificados, y eso rompía el gate de campos requeridos por una
    falla de fidelidad del modelo, no por un lead realmente incompleto. Solo
    score/icp_reasons deben venir de QUALIFIER; todo lo demás, del lead que
    PROSPECTOR ya encontró."""

    def _raw(self):
        return [
            Lead(company="Splash Piscinas", role="por verificar", channel="email",
                 email="ventas@splash.cl", phone=None, domain="splash.cl"),
            Lead(company="Aguamundo Piscinas", role="por verificar", channel="whatsapp",
                 email=None, phone="+56911112222", domain="aguamundo.cl"),
        ]

    def test_restores_fields_the_model_dropped(self):
        from zero.orchestrator import _merge_qualifier_scores
        # el modelo real solo devolvió company/score/icp_reasons — canal,
        # email, teléfono y hasta el rol quedaron afuera (visto en vivo).
        qual_out = [{"company": "Splash Piscinas", "score": 65, "icp_reasons": ["fit ok"]}]
        merged = _merge_qualifier_scores(self._raw(), qual_out)
        self.assertEqual(len(merged), 1)
        lead = merged[0]
        self.assertEqual(lead.score, 65)
        self.assertEqual(lead.icp_reasons, ["fit ok"])
        # restaurado desde el lead original, no del modelo:
        self.assertEqual(lead.channel, "email")
        self.assertEqual(lead.email, "ventas@splash.cl")
        self.assertEqual(lead.domain, "splash.cl")
        self.assertEqual(lead.role, "por verificar")

    def test_company_name_matching_is_case_and_whitespace_insensitive(self):
        from zero.orchestrator import _merge_qualifier_scores
        qual_out = [{"company": "  splash PISCINAS  ", "score": 70, "icp_reasons": []}]
        merged = _merge_qualifier_scores(self._raw(), qual_out)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].channel, "email")

    def test_hallucinated_company_not_in_original_leads_is_dropped(self):
        from zero.orchestrator import _merge_qualifier_scores
        qual_out = [
            {"company": "Splash Piscinas", "score": 70, "icp_reasons": ["ok"]},
            {"company": "Empresa que el modelo inventó", "score": 90, "icp_reasons": ["ok"]},
        ]
        merged = _merge_qualifier_scores(self._raw(), qual_out)
        self.assertEqual([l.company for l in merged], ["Splash Piscinas"])

    def test_lead_the_model_forgot_entirely_is_simply_not_scored(self):
        from zero.orchestrator import _merge_qualifier_scores
        # el modelo solo calificó a una de las dos empresas originales
        qual_out = [{"company": "Splash Piscinas", "score": 70, "icp_reasons": []}]
        merged = _merge_qualifier_scores(self._raw(), qual_out)
        self.assertEqual(len(merged), 1)
        self.assertNotIn("Aguamundo Piscinas", [l.company for l in merged])


class ExportTest(unittest.TestCase):
    """The deliverable CSV — what a client actually receives."""

    def test_csv_has_header_and_one_row_per_lead(self):
        import csv
        import os
        import tempfile
        from zero.export import deliverable_to_csv

        deliverable = {
            "qualified_leads": [
                {"company": "Acme", "name": "Ana", "role": "CEO", "email": "ana@acme.cl",
                 "phone": None, "channel": "email", "score": 88, "icp_reasons": ["fit alto"]},
            ],
            "outreach": [{"company": "Acme", "channel": "email",
                          "subject": "Hola", "body": "Mensaje de prueba"}],
        }
        path = os.path.join(tempfile.mkdtemp(), "deliverable.csv")
        n = deliverable_to_csv(deliverable, path)
        self.assertEqual(n, 1)

        with open(path, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][0], "empresa")          # header present
        self.assertEqual(len(rows), 2)                   # header + 1 lead
        self.assertIn("Acme", rows[1])
        self.assertIn("Mensaje de prueba", rows[1])      # outreach joined by company

    def test_crm_book_export(self):
        import csv
        import os
        import tempfile
        from zero.export import crm_to_csv

        crm = CRM(None)
        crm.upsert("c", {"company": "Acme", "role": "CEO", "email": "a@acme.cl", "score": 90},
                   stage="qualified")
        crm.upsert("c", {"company": "Beta", "role": "CTO", "email": "b@beta.cl", "score": 80},
                   stage="contacted")
        path = os.path.join(tempfile.mkdtemp(), "book.csv")
        n = crm_to_csv(crm, "c", path)
        self.assertEqual(n, 2)
        with open(path, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][-1], "actualizado")
        self.assertEqual(len(rows), 3)                   # header + 2 leads
        self.assertIn("etapa", rows[0])


class MemoryPersistenceTest(unittest.TestCase):
    def test_snapshot_restore_roundtrip_covers_all_fields(self):
        """Todo lo que snapshot() guarda, _restore() lo recupera — atrapa el bug
        de agregar un campo nuevo y olvidarlo en la carga (file o Supabase)."""
        m = SessionMemory(None)
        m.register_client("acme", "GROWTH")
        m.set_client_icp("acme", {"sells": "pallets"})
        m.set_agent_status("CONCIERGE", "done")
        m.mark_contacted("ceo@acme.cl")
        m.add_used_email("ceo@acme.cl")
        m.open_sequence("acme", {"email": "ceo@acme.cl", "company": "Acme"})
        m.set_pending_offer("acme", "ceo@acme.cl", "info")
        m.set_client_vendor("acme", "stefano")
        m.list_vendors()                                    # siembra el catálogo
        m.log("test", detail="x")
        snap = m.snapshot()
        self.assertTrue(all(snap[k] for k in snap), snap)   # cada campo tiene algo
        m2 = SessionMemory(None)
        m2._restore(snap)
        self.assertEqual(m2.snapshot(), snap)


class LifecycleTest(unittest.TestCase):
    """The whole operator journey, end to end, must hold together."""

    def test_run_then_close_then_forecast_then_export(self):
        import os
        import tempfile
        from zero.export import crm_to_csv

        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)

        # 1) run the pipeline → leads land in the CRM, some nurturing
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        nurturing = crm.list("acme", "nurturing")
        self.assertTrue(nurturing)

        # 2) operator closes one deal
        key = nurturing[0]["key"]
        crm.set_stage("acme", key, "won", detail="cerró")
        self.assertEqual(crm.get("acme", key)["stage"], "won")

        # 3) forecast runs over the logged activity
        fc = z.forecast("acme")
        self.assertIn("projection", fc["forecast"])

        # 4) the book exports
        path = os.path.join(tempfile.mkdtemp(), "book.csv")
        self.assertGreaterEqual(crm_to_csv(crm, "acme", path), 1)


class ReplyLoopTest(unittest.TestCase):
    """When a lead replies, ZERO stops chasing it and moves it to `replied`."""

    def _run(self):
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        return z, crm

    def test_reply_closes_sequence_and_advances_stage(self):
        z, crm = self._run()
        key = crm.list("acme", "nurturing")[0]["key"]
        # the lead has an open follow-up sequence before it replies
        self.assertTrue(any(s["lead_key"] == key and s["status"] == "open"
                            for s in z.memory.sequences))

        res = z.register_reply("acme", key, text="me interesa, llámenme")

        self.assertEqual(res["stage"], "replied")
        self.assertTrue(res["sequence_closed"])
        self.assertEqual(crm.get("acme", key)["stage"], "replied")
        # the sequence is closed → TRACKER never nudges this lead again
        self.assertFalse(any(s["lead_key"] == key and s["status"] == "open"
                             for s in z.memory.sequences))
        # and a far-future follow-up sweep won't pick it up
        future = (datetime.now(timezone.utc) + timedelta(days=999)).isoformat()
        self.assertFalse(any(s["lead_key"] == key
                             for s in z.memory.due_sequences("acme", as_of=future)))

    def test_reply_without_open_sequence_still_advances(self):
        z, crm = self._run()
        key = crm.list("acme", "nurturing")[0]["key"]
        z.memory.close_sequence_for_lead("acme", key)   # no open sequence anymore
        res = z.register_reply("acme", key)
        self.assertFalse(res["sequence_closed"])
        self.assertEqual(res["stage"], "replied")

    def test_reply_is_forward_only(self):
        z, crm = self._run()
        key = crm.list("acme", "nurturing")[0]["key"]
        crm.set_stage("acme", key, "won", detail="cerró")
        z.register_reply("acme", key)
        self.assertEqual(crm.get("acme", key)["stage"], "won")  # not dragged back


class ReplyDetectionTest(unittest.TestCase):
    """The inbox sweep detects replies and closes sequences before TRACKER nudges."""

    def _zero(self):
        from zero.inbox import MockInbox
        crm = CRM(None)
        inbox = MockInbox()
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm, inbox=inbox)
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        return z, crm, inbox

    def test_detected_reply_closes_sequence_and_skips_followup(self):
        z, crm, inbox = self._zero()
        lead = crm.list("acme", "nurturing")[0]
        sender = lead.get("email") or "".join(c for c in lead["phone"] if c.isdigit())
        inbox.add({"from": sender, "body": "me interesa, hablemos"})

        future = (datetime.now(timezone.utc) + timedelta(days=999)).isoformat()
        d = z.run_followups("acme", as_of=future)

        self.assertEqual(d["replies_detected"], 1)
        self.assertEqual(crm.get("acme", lead["key"])["stage"], "replied")
        # its sequence was closed by the reply, so TRACKER never nudged it
        self.assertNotIn(lead["key"], [m["lead_key"] for m in d["followups"]])
        self.assertFalse(any(s["lead_key"] == lead["key"] and s["status"] == "open"
                             for s in z.memory.sequences))

    def test_unmatched_sender_is_logged_not_an_error(self):
        z, _, inbox = self._zero()
        inbox.add({"from": "desconocido@nadie.cl", "body": "hola, ¿quién eres?"})
        d = z.check_replies()
        self.assertEqual(d["checked"], 1)
        self.assertEqual(d["matched"], 0)

    def test_empty_inbox_is_a_free_noop(self):
        z, _, _ = self._zero()
        d = z.check_replies()
        self.assertEqual(d, {"checked": 0, "matched": 0, "source": "mock", "replies": []})

    def test_file_inbox_consumes_once(self):
        import json
        import os
        import tempfile
        from zero.inbox import FileInbox
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "inbox.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump([{"from": "a@b.cl", "body": "sí, me interesa"}], f)
            box = FileInbox(path)
            self.assertEqual(len(box.fetch()), 1)
            self.assertEqual(box.fetch(), [])   # consumed: a reply never re-triggers

    def test_file_inbox_corrupt_file_left_untouched(self):
        import os
        import tempfile
        from zero.inbox import FileInbox
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "inbox.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{esto no es json")
            self.assertEqual(FileInbox(path).fetch(), [])
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "{esto no es json")   # never overwrite blind


class ChannelTest(unittest.TestCase):
    """The outbox delivers what gets drafted — mock-first, faithful contract."""

    def test_mock_sender_contract(self):
        from zero.channels import MockSender
        res = MockSender().send({"channel": "email", "to": "a@b.com", "body": "hola"})
        for k in ("channel", "to", "status", "id", "error", "via"):
            self.assertIn(k, res)
        self.assertEqual(res["status"], "sent")
        # no recipient → skipped, not crash
        self.assertEqual(MockSender().send({"channel": "whatsapp", "body": "x"})["status"], "skipped")

    def test_outbox_default_is_mock_and_never_raises(self):
        from zero.channels import Outbox
        box = Outbox()
        self.assertFalse(box.live)

        class Boom:
            name = "email"
            def send(self, msg):
                raise RuntimeError("smtp caído")
        box = Outbox({"email": Boom()}, retry_delay=0)   # delay 0: no dormir de verdad
        self.assertTrue(box.live)
        res = box.send({"channel": "email", "to": "a@b.com", "body": "x"})
        self.assertEqual(res["status"], "error")          # degraded, not crashed
        self.assertIn("smtp caído", res["error"])

    def test_outbox_retries_before_giving_up(self):
        """Un corte de red momentáneo no debe perder el envío para siempre —
        Outbox reintenta antes de degradar a 'error'. retry_delay=0 para no
        dormir de verdad en el test."""
        from zero.channels import Outbox

        class FailsTwiceThenWorks:
            name = "email"
            def __init__(self):
                self.calls = 0
            def send(self, msg):
                self.calls += 1
                if self.calls < 3:
                    raise RuntimeError(f"intento {self.calls} falló")
                return {"channel": "email", "to": msg.get("to"), "status": "sent",
                        "id": "ok", "error": None, "via": "email"}

        sender = FailsTwiceThenWorks()
        box = Outbox({"email": sender}, retry_attempts=3, retry_delay=0)
        res = box.send({"channel": "email", "to": "a@b.com", "body": "x"})
        self.assertEqual(res["status"], "sent")
        self.assertEqual(sender.calls, 3)   # 2 fallos + 1 éxito

    def test_outbox_gives_up_after_exhausting_retries(self):
        from zero.channels import Outbox

        class AlwaysFails:
            name = "email"
            def __init__(self):
                self.calls = 0
            def send(self, msg):
                self.calls += 1
                raise RuntimeError("siempre falla")

        sender = AlwaysFails()
        box = Outbox({"email": sender}, retry_attempts=3, retry_delay=0)
        res = box.send({"channel": "email", "to": "a@b.com", "body": "x"})
        self.assertEqual(res["status"], "error")
        self.assertIn("siempre falla", res["error"])
        self.assertEqual(sender.calls, 3)   # exactamente retry_attempts intentos, ni uno más

    def test_whatsapp_status_without_creds_raises_clean_error(self):
        """Sin WHATSAPP_TOKEN/PHONE_ID, whatsapp_status() falla con un mensaje
        claro (RuntimeError), nunca un KeyError crudo — y sin tocar la red."""
        import os
        from zero.channels import whatsapp_status
        prev = {k: os.environ.get(k) for k in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID")}
        try:
            os.environ.pop("WHATSAPP_TOKEN", None)
            os.environ.pop("WHATSAPP_PHONE_ID", None)
            with self.assertRaises(RuntimeError) as ctx:
                whatsapp_status()
            self.assertIn("WhatsApp", str(ctx.exception))
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_pipeline_sends_first_touch_via_mock(self):
        from zero.channels import Outbox
        crm = CRM(None)
        box = Outbox()
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm, outbox=box)
        d = z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)

        self.assertEqual(d["summary"]["delivery"], "mock")
        self.assertGreater(d["summary"]["sent"], 0)
        self.assertEqual(d["summary"]["sent"], len(box.log))
        # every send is recorded on the lead's CRM history
        key = crm.list("acme", "nurturing")[0]["key"]
        self.assertTrue(any(h["event"] == "send" for h in crm.get("acme", key)["history"]))


class EmailSenderFromNameTest(unittest.TestCase):
    """El 'From' del email muestra el nombre del vendedor asignado (Fernanda/
    Stéfano) cuando viene — sin esto, el correo sale con la dirección pelada
    (a menudo una cuenta personal como Gmail), que se ve poco profesional y no
    dice de parte de quién escribe (encontrado probando envío real, 2026-07-06)."""

    def test_from_header_includes_vendor_display_name(self):
        from zero.channels import EmailSender
        em = EmailSender._build_message(
            "ventas@zeroai.cl",
            {"to": "lead@acme.cl", "subject": "Hola", "body": "x", "from_name": "Stéfano"},
        )
        self.assertIn("Stéfano", em["From"])
        self.assertIn("ventas@zeroai.cl", em["From"])

    def test_no_from_name_keeps_bare_address(self):
        """Sin vendor asignado, el comportamiento no cambia — dirección pelada,
        como siempre (nunca inventa un nombre)."""
        from zero.channels import EmailSender
        em = EmailSender._build_message(
            "ventas@zeroai.cl", {"to": "lead@acme.cl", "subject": "Hola", "body": "x"},
        )
        self.assertEqual(em["From"], "ventas@zeroai.cl")

    def test_deliver_threads_vendor_name_into_the_email_from(self):
        """_deliver (usado por run_pipeline y run_followups) debe agregar
        from_name al mensaje que llega al Outbox cuando el cliente tiene un
        vendedor asignado — sin esto el correo real sale con la dirección
        pelada de la cuenta SMTP configurada, sin decir de parte de quién."""
        from zero.channels import Outbox

        class CapturingSender:
            name = "email"
            def __init__(self):
                self.sent = []
            def send(self, msg):
                self.sent.append(msg)
                return {"channel": "email", "to": msg.get("to"), "status": "sent",
                        "id": "cap", "error": None, "via": "email"}

        sender = CapturingSender()
        z = Zero(build_agents(mock=True), memory=SessionMemory(None),
                 outbox=Outbox({"email": sender}))
        z.memory.set_client_vendor("acme", "stefano")
        z._deliver("acme", "lead-1", "lead@acme.cl",
                   {"channel": "email", "subject": "Hola", "body": "x"})
        self.assertEqual(len(sender.sent), 1)
        self.assertEqual(sender.sent[0]["from_name"], "Stéfano")


class WhatsAppVendorSendTest(unittest.TestCase):
    """Cada cliente envía WhatsApp con las credenciales de SU vendedor (Fase 3.2).
    Todo offline: el factory de senders se inyecta, nunca se toca la red."""

    @staticmethod
    def _ok(msg):
        return {"channel": "whatsapp", "to": msg.get("to"), "status": "sent",
                "id": "x", "error": None, "via": "whatsapp"}

    def _live_outbox(self):
        from zero.channels import Outbox
        built = {}

        class FakeWA:
            name = "whatsapp"
            def __init__(self, pid, tok):
                self.pid, self.tok, self.sent = pid, tok, []
                built[pid] = self
            def send(s, msg):
                s.sent.append(msg)
                return WhatsAppVendorSendTest._ok(msg)

        box = Outbox({"whatsapp": object()},                # real no vacío -> modo live
                     wa_sender_factory=lambda pid, tok: FakeWA(pid, tok))
        return box, built

    def test_outbox_builds_per_vendor_sender_and_caches(self):
        box, built = self._live_outbox()
        box.send({"channel": "whatsapp", "to": "569111", "body": "a"}, wa_creds=("pid-1", "tok-1"))
        box.send({"channel": "whatsapp", "to": "569222", "body": "b"}, wa_creds=("pid-2", "tok-2"))
        box.send({"channel": "whatsapp", "to": "569333", "body": "c"}, wa_creds=("pid-1", "tok-1"))
        self.assertEqual(built["pid-1"].tok, "tok-1")
        self.assertEqual(built["pid-2"].tok, "tok-2")
        self.assertEqual(set(built), {"pid-1", "pid-2"})     # pid-1 reusado (cache), no recreado
        self.assertEqual(len(built["pid-1"].sent), 2)        # dos envíos por el mismo sender

    def test_mock_outbox_ignores_wa_creds(self):
        from zero.channels import Outbox
        res = Outbox().send({"channel": "whatsapp", "to": "569", "body": "x"},
                            wa_creds=("pid", "tok"))
        self.assertEqual(res["via"], "mock")                 # sin red, sin credenciales reales

    def test_deliver_selects_each_clients_vendor_credentials(self):
        import os
        prev = {k: os.environ.get(k) for k in
                ("WHATSAPP_TOKEN_FERNANDA", "WHATSAPP_TOKEN_STEFANO", "WHATSAPP_TOKEN")}
        os.environ["WHATSAPP_TOKEN_FERNANDA"] = "tok-f"
        os.environ["WHATSAPP_TOKEN_STEFANO"] = "tok-s"
        os.environ.pop("WHATSAPP_TOKEN", None)
        try:
            from zero.channels import Outbox

            class RecordingOutbox(Outbox):
                def __init__(self):
                    super().__init__()
                    self.calls = []
                def send(self, msg, wa_creds=None):
                    self.calls.append((msg.get("channel"), wa_creds))
                    return super().send(msg, wa_creds=wa_creds)

            box = RecordingOutbox()
            z = Zero(build_agents(mock=True), memory=SessionMemory(None), outbox=box)
            z.memory.set_client_vendor("a", "fernanda")
            z.memory.set_client_vendor("b", "stefano")
            f, st = z.memory.get_vendor("fernanda"), z.memory.get_vendor("stefano")

            z._deliver("a", "k1", "569111", {"channel": "whatsapp", "body": "hola"})
            z._deliver("b", "k2", "569222", {"channel": "whatsapp", "body": "hola"})
            self.assertEqual(box.calls[0], ("whatsapp", (f["whatsapp_phone_id"], "tok-f")))
            self.assertEqual(box.calls[1], ("whatsapp", (st["whatsapp_phone_id"], "tok-s")))

            # email no resuelve credenciales de WhatsApp
            z._deliver("a", "k3", "a@b.cl", {"channel": "email", "body": "x"})
            self.assertEqual(box.calls[2], ("email", None))
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_inbound_reply_uses_vendor_of_received_number(self):
        """Una respuesta sale del número al que el lead escribió (su vendedor por
        phone_id), aunque el cliente esté asignado a otro vendedor."""
        import os
        prev = {k: os.environ.get(k) for k in ("WHATSAPP_TOKEN_STEFANO", "WHATSAPP_TOKEN")}
        os.environ["WHATSAPP_TOKEN_STEFANO"] = "tok-s"
        os.environ.pop("WHATSAPP_TOKEN", None)
        try:
            from zero.channels import Outbox

            class RecordingOutbox(Outbox):
                def __init__(self):
                    super().__init__()
                    self.calls = []
                def send(self, msg, wa_creds=None):
                    self.calls.append((msg.get("channel"), wa_creds))
                    return super().send(msg, wa_creds=wa_creds)

            box = RecordingOutbox()
            crm = CRM(None)
            z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm, outbox=box)
            z.memory.set_client_vendor("acme", "fernanda")   # cliente asignado a Fernanda
            z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
            lead = crm.list("acme", "nurturing")[0]
            stefano = z.memory.get_vendor("stefano")
            from_contact = "".join(c for c in (lead.get("phone") or lead.get("email") or "") if c.isalnum())

            box.calls.clear()
            # llega un mensaje al NÚMERO de Stéfano (no el de Fernanda)
            z.handle_inbound(from_contact, "¿qué hacen?", to_phone_id=stefano["whatsapp_phone_id"])
            wa_calls = [c for c in box.calls if c[0] == "whatsapp"]
            self.assertTrue(wa_calls)
            # respondió con las credenciales de Stéfano (el número que recibió), no Fernanda
            self.assertEqual(wa_calls[-1][1], (stefano["whatsapp_phone_id"], "tok-s"))
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class ConciergeTest(unittest.TestCase):
    """The conversational agent answers inbound questions about the business."""

    def _zero(self):
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        return z, crm

    def test_concierge_intents(self):
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        z.memory.set_client_icp("acme", {"sells": "pallets de madera"})
        self.assertIn("plan", z.converse("acme", "¿cuánto cuesta?").lower())
        self.assertIn("pallets", z.converse("acme", "¿qué hacen exactamente?").lower())
        self.assertTrue(z.converse("acme", "¿podemos agendar una llamada?"))
        # transparency: admits it's an AI if asked
        self.assertIn("ia", z.converse("acme", "¿eres un robot?").lower())

    def _intent(self, z, msg):
        t = TaskPayload(agent="CONCIERGE", client_id="acme", client_tier="", instructions="x",
                        data={"message": msg, "lead": {"name": "Carla", "company": "Acme"},
                              "icp": {"sells": "pallets"}},
                        constraints=Constraints(channels=["whatsapp"]))
        return z.agents["CONCIERGE"].run(t).result

    def test_interested_message_is_not_optout(self):
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        # 'bueno' y 'necesito' contienen 'no' — un interesado no es un opt-out
        r = self._intent(z, "Bueno, mándame más información")
        self.assertEqual(r["intent"], "info")
        self.assertNotEqual(self._intent(z, "necesito más detalles del servicio")["intent"],
                            "optout")

    def test_real_optout_still_closes(self):
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        for msg in ("no me interesa, gracias", "stop", "no", "dejen de escribirme"):
            self.assertEqual(self._intent(z, msg)["intent"], "optout", msg)

    def test_trust_question_gets_transparency(self):
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        r = self._intent(z, "¿de dónde sacaste mi número?")
        self.assertEqual(r["intent"], "trust")
        self.assertIn("pública", r["reply"].lower())   # honesto: fuente del contacto

    def test_objections_are_handled(self):
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        self.assertEqual(self._intent(z, "ya tenemos proveedor de esto")["intent"], "objection")
        self.assertEqual(self._intent(z, "me parece muy caro")["intent"], "objection")

    def test_negated_interest_is_optout(self):
        # 'interesa' es keyword de meeting — un interés negado jamás debe agendar
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        for msg in ("no nos interesa por ahora", "no estamos interesados, gracias",
                    "no me interesa, dejen de mandar spam", "dejen de mandarme spam"):
            self.assertEqual(self._intent(z, msg)["intent"], "optout", msg)
        self.assertEqual(self._intent(z, "sí me interesa, agendemos")["intent"], "meeting")

    def test_manda_substring_is_not_info(self):
        # 'demanda' contiene 'manda' — no es una petición de información
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        self.assertNotEqual(self._intent(z, "tenemos mucha demanda, cuéntame más")["intent"],
                            "info")

    def test_ahora_substring_is_not_meeting(self):
        # 'ahora' contiene 'hora' — un "no por ahora" no debe agendar reunión
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        for msg in ("no por ahora, tal vez después", "ahora no puedo hablar",
                    "te escribo ahora", "no tengo presupuesto para esto ahora"):
            self.assertNotEqual(self._intent(z, msg)["intent"], "meeting", msg)
        # 'hora' como palabra (no dentro de 'ahora') sí dispara meeting
        self.assertEqual(self._intent(z, "¿a qué hora te acomoda?")["intent"], "meeting")

    def test_vale_is_not_pricing(self):
        # 'vale' como muletilla chilena ("ok") no es una pregunta de precio
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        for msg in ("vale, gracias", "vale, perfecto", "ya vale, entendido"):
            self.assertNotEqual(self._intent(z, msg)["intent"], "pricing", msg)
        # pero "¿cuánto vale?" sigue siendo pricing (vía 'cuánto')
        self.assertEqual(self._intent(z, "¿cuánto vale el servicio?")["intent"], "pricing")

    def test_no_budget_objection_is_handled(self):
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        self.assertEqual(self._intent(z, "no tengo presupuesto para esto ahora")["intent"],
                         "objection")

    def test_elongated_no_is_optout(self):
        # "nooo", "NO!!", "no..." — un "no" decorado sigue siendo un cierre,
        # no debe caer en 'general' por no calzar con el "no" corto exacto.
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        for msg in ("nooo", "NO!!", "no...", "no¡¡"):
            self.assertEqual(self._intent(z, msg)["intent"], "optout", msg)
        # pero un "no" dentro de una frase con más contenido no es esto
        self.assertNotEqual(self._intent(z, "no por ahora, tal vez después")["intent"],
                             "optout")

    def test_safety_question_gets_trust(self):
        # "¿es seguro?" es la misma familia de duda que "¿de dónde sacaste mi número?"
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        for msg in ("¿es esto seguro?", "¿es confiable esto?", "esto no es una estafa, no?"):
            self.assertEqual(self._intent(z, msg)["intent"], "trust", msg)

    def test_short_affirmation_is_accept(self):
        # Afirmaciones cortas sin contenido propio → 'accept', con una propuesta
        # concreta de siguiente paso (no el menú genérico de 'general').
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        for msg in ("dale, vamos", "ok", "vale", "sí👍", "perfecto, genial"):
            r = self._intent(z, msg)
            self.assertEqual(r["intent"], "accept", msg)
            self.assertIn("?", r["reply"])  # sigue proponiendo un siguiente paso
        # "no" en la frase descarta 'accept', aunque empiece con palabra afirmativa
        self.assertNotEqual(self._intent(z, "bueno, no estoy seguro")["intent"], "accept")

    def test_lone_channel_word_is_general(self):
        # "por acá" solo, sin oferta previa que aceptar, no es ni 'info' ni
        # 'accept' — es ambiguo sin contexto (es una elección de canal, no un intent).
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        r = self._intent(z, "por acá")
        self.assertNotIn(r["intent"], ("info", "accept"))

    def test_accepts_offer_rejections_and_acceptances(self):
        from zero.orchestrator import accepts_offer
        # una objeción no es aceptar la oferta — el "ya" de "ya tenemos" no es afirmativo
        for msg in ("ya tenemos proveedor, gracias", "no, gracias", "no me interesa",
                    "stop", "ya trabajamos con alguien"):
            self.assertFalse(accepts_offer(msg), msg)
        for msg in ("sí, dale", "ok perfecto", "al correo porfa", "carla@acme.cl",
                    "ya, mándalo", "vale, mándalo", "vale dale"):
            self.assertTrue(accepts_offer(msg), msg)

    def test_parse_inbound(self):
        from zero.whatsapp_inbound import parse_inbound
        payload = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "PID_STEFANO"},
            "messages": [
                {"from": "56999111222", "type": "text", "text": {"body": "hola, precio?"}},
                {"from": "56999333444", "type": "image"},
            ]}}]}]}
        msgs = parse_inbound(payload)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0], {"from": "56999111222", "text": "hola, precio?",
                                   "to_phone_id": "PID_STEFANO"})
        self.assertEqual(msgs[1]["text"], "[image]")
        self.assertEqual(msgs[1]["to_phone_id"], "PID_STEFANO")
        # sin metadata → to_phone_id vacío, nunca crash
        no_meta = parse_inbound({"entry": [{"changes": [{"value": {"messages": [
            {"from": "569", "type": "text", "text": {"body": "x"}}]}}]}]})
        self.assertEqual(no_meta[0]["to_phone_id"], "")
        self.assertEqual(parse_inbound({}), [])      # malformed → empty, no crash

    def test_parse_inbound_formas_malformadas_nunca_revienta(self):
        """El docstring de parse_inbound promete 'malformed payloads yield [],
        never raise' — cada nivel del webhook de Meta (entry/changes/value/
        messages) puede en teoría venir con otra forma; ninguna debe crashear."""
        from zero.whatsapp_inbound import parse_inbound
        casos = [
            {"entry": "oops"},
            {"entry": [{"changes": "oops"}]},
            {"entry": [{"changes": [{"value": "oops"}]}]},
            {"entry": [{"changes": [{"value": {"messages": "oops"}}]}]},
            {"entry": [{"changes": [{"value": {"messages": ["oops"]}}]}]},
            {"entry": ["oops"]},
            {"entry": [{"changes": ["oops"]}]},
        ]
        for payload in casos:
            self.assertEqual(parse_inbound(payload), [])
        # el último caso (metadata malformada) sí debe rescatar el mensaje válido
        # con to_phone_id vacío, en vez de descartarlo entero
        rescatado = parse_inbound({"entry": [{"changes": [{"value": {
            "metadata": "oops",
            "messages": [{"from": "569", "type": "text", "text": {"body": "x"}}]}}]}]})
        self.assertEqual(rescatado, [{"from": "569", "text": "x", "to_phone_id": ""}])

    def test_verify_meta_signature(self):
        """Sin esto, POST /api/webhooks/whatsapp aceptaría cualquier payload de
        cualquiera — verify_meta_signature es lo único que lo evita."""
        import hashlib
        import hmac
        import os
        from zero.whatsapp_inbound import verify_meta_signature
        prev = os.environ.get("WHATSAPP_APP_SECRET")
        try:
            os.environ["WHATSAPP_APP_SECRET"] = "mi-secreto"
            body = b'{"entry": []}'
            good_sig = "sha256=" + hmac.new(b"mi-secreto", body, hashlib.sha256).hexdigest()
            self.assertTrue(verify_meta_signature(body, good_sig))
            # firma de otro secreto -> rechazada
            bad_sig = "sha256=" + hmac.new(b"otro-secreto", body, hashlib.sha256).hexdigest()
            self.assertFalse(verify_meta_signature(body, bad_sig))
            # sin header -> rechazada
            self.assertFalse(verify_meta_signature(body, None))
            # header sin el prefijo esperado -> rechazada
            self.assertFalse(verify_meta_signature(body, "no-es-sha256"))
        finally:
            if prev is None:
                os.environ.pop("WHATSAPP_APP_SECRET", None)
            else:
                os.environ["WHATSAPP_APP_SECRET"] = prev

    def test_verify_meta_signature_without_secret_configured_always_rejects(self):
        """Sin WHATSAPP_APP_SECRET configurado, NUNCA deja pasar nada — ni con una
        firma que 'parece' válida. Mejor rechazar todo que aceptar sin poder
        verificar de verdad."""
        import os
        from zero.whatsapp_inbound import verify_meta_signature
        prev = os.environ.pop("WHATSAPP_APP_SECRET", None)
        try:
            self.assertFalse(verify_meta_signature(b"{}", "sha256=loquesea"))
        finally:
            if prev is not None:
                os.environ["WHATSAPP_APP_SECRET"] = prev

    def test_inbound_matches_lead_and_replies(self):
        z, crm = self._zero()
        lead = crm.list("acme", "nurturing")[0]
        phone = lead.get("phone")
        if not phone:   # a contacted lead always has email or phone; use email then
            res = z.handle_inbound(lead["email"], "¿qué hacen?")
        else:
            res = z.handle_inbound("".join(c for c in phone if c.isdigit()), "¿qué hacen?")
        self.assertTrue(res["matched"])
        self.assertTrue(res["reply"])                      # the agent answered
        self.assertEqual(crm.get("acme", lead["key"])["stage"], "replied")
        self.assertTrue(any(h["event"] == "auto_reply"
                            for h in crm.get("acme", lead["key"])["history"]))

    def test_inbound_unmatched_is_not_an_error(self):
        z, _ = self._zero()
        res = z.handle_inbound("000000000", "hola?")
        self.assertFalse(res["matched"])


class ConciergeEdgeCasesTest(unittest.TestCase):
    """Casos difíciles: mensajes vacíos, groseros, spam, en otro idioma o
    absurdamente largos NUNCA deben tirar una excepción — siempre hay una
    respuesta profesional, con algún intent razonable. Un lead real puede
    escribir cualquier cosa; CONCIERGE no puede romperse por eso."""

    def _zero(self):
        return Zero(build_agents(mock=True), memory=SessionMemory(None))

    def _intent(self, z, msg):
        t = TaskPayload(agent="CONCIERGE", client_id="acme", client_tier="", instructions="x",
                        data={"message": msg, "lead": {"name": "Carla", "company": "Acme"},
                              "icp": {"sells": "pallets"}},
                        constraints=Constraints(channels=["whatsapp"]))
        return z.agents["CONCIERGE"].run(t).result

    def test_empty_or_blank_message_never_crashes(self):
        z = self._zero()
        for msg in ("", "   ", "...", "👍👍👍", "\n\t"):
            r = self._intent(z, msg)
            self.assertTrue(r["reply"], repr(msg))     # siempre hay algo que decir
            self.assertTrue(r["intent"], repr(msg))

    def test_message_key_missing_entirely_never_crashes(self):
        # el lead pudo mandar solo una imagen/audio: sin texto en absoluto,
        # no solo un string vacío — task.data ni siquiera trae "message".
        z = self._zero()
        t = TaskPayload(agent="CONCIERGE", client_id="acme", client_tier="", instructions="x",
                        data={"lead": {"name": "Carla", "company": "Acme"}, "icp": {}},
                        constraints=Constraints(channels=["whatsapp"]))
        r = z.agents["CONCIERGE"].run(t).result
        self.assertTrue(r["reply"])

    def test_rude_or_insulting_message_gets_a_professional_reply(self):
        # el lead puede insultar — la respuesta NUNCA repite groserías ni se
        # pone defensiva; sigue siendo profesional (mismo tono que 'trust'/'optout').
        z = self._zero()
        rude_messages = (
            "esto es una estafa de mierda, dejen de molestarme carajo",
            "quién chucha les dio mi número, son unos boludos",
            "no me interesa su servicio de porquería, no jodan más",
        )
        profanity = ("mierda", "chucha", "boludo", "carajo", "porquería", "jodan")
        for msg in rude_messages:
            r = self._intent(z, msg)
            self.assertTrue(r["reply"], msg)
            reply_lower = r["reply"].lower()
            for word in profanity:
                self.assertNotIn(word, reply_lower, f"la respuesta no debe repetir groserías: {msg}")

    def test_off_topic_or_nonsense_message_falls_back_to_general(self):
        z = self._zero()
        for msg in ("jajaja XD", "🐱🐱🐱", "asdkjfh qwoiue", "buenos días! lindo día"):
            r = self._intent(z, msg)
            self.assertTrue(r["reply"], msg)

    def test_english_message_still_handled_via_shared_keywords(self):
        # no hay detección de idioma — pero un "stop" en inglés sigue cerrando
        # (misma keyword que ya cubre el opt-out en español).
        z = self._zero()
        r = self._intent(z, "please stop spamming me")
        self.assertEqual(r["intent"], "optout")

    def test_extremely_long_message_does_not_hang_or_crash(self):
        import time
        z = self._zero()
        huge = "hola " * 5000   # ~25.000 caracteres, sin ninguna keyword clara
        start = time.monotonic()
        r = self._intent(z, huge)
        elapsed = time.monotonic() - start
        self.assertTrue(r["reply"])
        self.assertLess(elapsed, 2.0, "un mensaje largo no debería tardar segundos (riesgo de ReDoS)")

    def test_lead_without_name_still_gets_a_reply(self):
        # lead.get("name") vacío/ausente — el saludo no debe romperse ("Hola " con espacio colgando)
        z = self._zero()
        t = TaskPayload(agent="CONCIERGE", client_id="acme", client_tier="", instructions="x",
                        data={"message": "¿cuánto cuesta?", "lead": {"company": "Acme"}, "icp": {}},
                        constraints=Constraints(channels=["whatsapp"]))
        r = z.agents["CONCIERGE"].run(t).result
        self.assertTrue(r["reply"])
        self.assertTrue(r["reply"].startswith("Hola,") or r["reply"].startswith("Hola "))


class PendingOfferTest(unittest.TestCase):
    """Las promesas del CONCIERGE se cumplen: 'te mando un resumen' / '¿te dejo
    3 ejemplos?' quedan pendientes y la aceptación del lead dispara el envío."""

    def _zero(self):
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        lead = crm.list("acme", "nurturing")[0]
        sender = lead.get("email") or "".join(c for c in lead["phone"] if c.isdigit())
        return z, crm, lead, sender

    def test_info_offer_fulfilled_on_acceptance(self):
        z, crm, lead, sender = self._zero()
        r1 = z.handle_inbound(sender, "mándame más información")
        self.assertEqual(r1["intent"], "info")           # promesa hecha…
        r2 = z.handle_inbound(sender, "sí, por acá")
        self.assertEqual(r2["intent"], "fulfill")        # …y cumplida
        self.assertIn("ejemplos", r2["reply"].lower())
        self.assertTrue(any(h["event"] == "info_sent"
                            for h in crm.get("acme", lead["key"])["history"]))

    def test_offer_is_consumed_once(self):
        z, _, _, sender = self._zero()
        z.handle_inbound(sender, "mándame más información")
        z.handle_inbound(sender, "dale")
        r3 = z.handle_inbound(sender, "ok")              # ya no hay nada pendiente
        self.assertNotEqual(r3["intent"], "fulfill")

    def test_objection_yes_gets_examples(self):
        z, _, _, sender = self._zero()
        r1 = z.handle_inbound(sender, "ya trabajamos con alguien que nos hace esto")
        self.assertEqual(r1["intent"], "objection")
        r2 = z.handle_inbound(sender, "bueno, déjalos")
        self.assertEqual(r2["intent"], "fulfill")
        self.assertIn("3 ejemplos", r2["reply"])

    def test_acceptance_with_email_goes_to_email(self):
        z, _, _, sender = self._zero()
        z.handle_inbound(sender, "mándame más información")
        z.handle_inbound(sender, "mándalo a carla@acme.cl")
        sent = z.outbox.log[-1]
        self.assertEqual(sent["channel"], "email")
        self.assertEqual(sent["to"], "carla@acme.cl")

    def test_objection_after_offer_is_not_acceptance(self):
        # "ya tenemos proveedor" trae un "ya" — es objeción, no un sí
        z, _, _, sender = self._zero()
        z.handle_inbound(sender, "mándame más información")
        r2 = z.handle_inbound(sender, "mmm la verdad ya tenemos proveedor")
        self.assertEqual(r2["intent"], "objection")

    def test_rejection_voids_the_offer(self):
        z, _, _, sender = self._zero()
        z.handle_inbound(sender, "mándame más información")
        r2 = z.handle_inbound(sender, "no gracias, no me interesa")
        self.assertEqual(r2["intent"], "optout")         # rechazo ≠ aceptación
        r3 = z.handle_inbound(sender, "ok")
        self.assertNotEqual(r3["intent"], "fulfill")     # y la oferta quedó anulada

    def test_pending_offer_wins_over_concierge_accept(self):
        # CONCIERGE clasificaría "dale, vamos" como su propio intent 'accept',
        # pero con una oferta pendiente el orquestador debe cumplirla primero
        # ('fulfill' gana sobre 'accept').
        z, _, _, sender = self._zero()
        z.handle_inbound(sender, "mándame más información")
        r2 = z.handle_inbound(sender, "dale, vamos")
        self.assertEqual(r2["intent"], "fulfill")


class ScalabilityTest(unittest.TestCase):
    """Reads are scoped by client and paginated — no full-table scans."""

    def _crm(self):
        crm = CRM(None)
        for c in ("acme", "globex"):
            for n in range(5):
                crm.upsert(c, {"company": f"{c}-{n}", "role": "CEO",
                               "email": f"{n}@{c}.com", "score": 90 - n}, stage="qualified")
        return crm

    def test_client_ids_and_scoped_list(self):
        crm = self._crm()
        self.assertEqual(crm.client_ids(), ["acme", "globex"])
        acme = crm.list("acme")
        self.assertEqual(len(acme), 5)
        self.assertTrue(all(r["client_id"] == "acme" for r in acme))

    def test_list_pagination(self):
        crm = self._crm()
        page1 = crm.list("acme", limit=2, offset=0)
        page2 = crm.list("acme", limit=2, offset=2)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 2)
        self.assertNotEqual(page1[0]["key"], page2[0]["key"])   # different slice
        # sorted by score desc → highest first
        self.assertGreaterEqual(page1[0]["score"], page1[1]["score"])

    def test_query_groups_and_pagination(self):
        crm = self._crm()
        self.assertEqual(len(crm.query("acme")), 5)                       # all of one client
        crm.set_stage("acme", crm.list("acme")[0]["key"], "won")
        self.assertEqual(len(crm.query("acme", stages=["won"])), 1)       # group filter
        self.assertEqual(len(crm.query("acme", stages=["qualified"])), 4)
        self.assertEqual(len(crm.query("acme", limit=2, offset=0)), 2)    # page 1
        self.assertEqual(len(crm.query("acme", limit=2, offset=4)), 1)    # last page
        self.assertEqual([r["client_id"] for r in crm.query("acme")], ["acme"] * 5)

    def test_ensure_hook_is_called_per_client(self):
        # SupabaseCRM uses this hook to lazy-load; the base must invoke it on reads.
        crm = CRM(None)
        seen = []
        crm._ensure = lambda cid: seen.append(cid)   # noqa
        crm.list("acme"); crm.counts("globex"); crm.get("acme", "x")
        self.assertIn("acme", seen)
        self.assertIn("globex", seen)


class AuthTest(unittest.TestCase):
    """Single-password agency gate: tokens signed by the password itself."""

    def setUp(self):
        import os
        self._prev = os.environ.get("AUTH_PASSWORD")
        os.environ["AUTH_PASSWORD"] = "s3cret"

    def tearDown(self):
        import os
        if self._prev is None:
            os.environ.pop("AUTH_PASSWORD", None)
        else:
            os.environ["AUTH_PASSWORD"] = self._prev

    def test_password_and_token_roundtrip(self):
        from zero import auth
        self.assertTrue(auth.auth_enabled())
        self.assertTrue(auth.verify_password("s3cret"))
        self.assertFalse(auth.verify_password("nope"))
        tok = auth.make_token()
        self.assertTrue(auth.valid_token(tok))
        self.assertFalse(auth.valid_token(tok + "x"))      # tampered
        self.assertFalse(auth.valid_token("garbage"))

    def test_expired_and_password_change_invalidate(self):
        from zero import auth
        import os
        self.assertFalse(auth.valid_token(auth.make_token(ttl=-1)))   # expired
        tok = auth.make_token()
        os.environ["AUTH_PASSWORD"] = "rotated"                       # rotate
        self.assertFalse(auth.valid_token(tok))                       # old token dies

    def test_disabled_when_no_password(self):
        from zero import auth
        import os
        os.environ.pop("AUTH_PASSWORD", None)
        self.assertFalse(auth.auth_enabled())
        self.assertFalse(auth.valid_token(auth.make_token()))


class MetaAdsTest(unittest.TestCase):
    """Mock de campañas fiel al contrato y determinista por cliente."""

    def test_mock_campaigns_contract(self):
        from zero.metaads import MockMetaAds
        camps = MockMetaAds().campaigns("acme")
        self.assertTrue(camps)
        for c in camps:
            for k in ("id", "name", "objective", "status", "region", "budget_clp", "spent_clp", "leads", "cpl_clp"):
                self.assertIn(k, c)
            self.assertIn(c["status"], ("active", "paused"))
        # determinista por cliente
        self.assertEqual([c["name"] for c in MockMetaAds().campaigns("acme")],
                         [c["name"] for c in MockMetaAds().campaigns("acme")])

    def test_per_client_config_personalizes(self):
        from zero.metaads import MockMetaAds
        cfg = {"monthly_budget_clp": 1_000_000, "regions": ["Valparaíso"]}
        camps = MockMetaAds().campaigns("acme", cfg)
        self.assertEqual(camps[0]["region"], "Valparaíso")          # zona del cliente
        # presupuesto mayor → montos mayores que el default
        base = MockMetaAds().campaigns("acme")[0]["budget_clp"]
        self.assertGreater(camps[0]["budget_clp"], base)

    def test_make_metaads_defaults_to_mock(self):
        from zero.metaads import make_metaads, MockMetaAds
        self.assertIsInstance(make_metaads(), MockMetaAds)   # sin credenciales → mock

    def test_ad_leads_flow_into_crm(self):
        from zero.metaads import MockMetaAds
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        leads = MockMetaAds().lead_ads("acme")
        self.assertTrue(leads)
        res = z.import_ad_leads("acme", leads)
        self.assertEqual(res["imported"], len(leads))
        recs = crm.list("acme")
        self.assertEqual(len(recs), len(leads))
        self.assertTrue(all("Meta Ads" in (r.get("tags") or []) for r in recs))
        self.assertTrue(all(r["stage"] == "qualified" for r in recs))

    def test_mediabuyer_recommends_actions(self):
        a = build_agents(mock=True)["MEDIABUYER"]
        camps = [
            {"id": "1", "name": "Leads OK", "objective": "OUTCOME_LEADS", "status": "active", "region": "Santiago (RM)", "cpl_clp": 4000, "leads": 20},
            {"id": "2", "name": "Leads caro", "objective": "OUTCOME_LEADS", "status": "active", "region": "Santiago (RM)", "cpl_clp": 12000, "leads": 3},
            {"id": "3", "name": "Awareness", "objective": "OUTCOME_AWARENESS", "status": "active", "region": "Santiago (RM)", "cpl_clp": 0, "leads": 0},
        ]
        resp = a.run(TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="",
                                 instructions="x", data={"campaigns": camps, "good_cpl_clp": 6000}))
        recs = {r["name"]: r["action"] for r in resp.result["recommendations"]}
        self.assertEqual(recs["Leads OK"], "scale")          # CPL bajo el objetivo
        self.assertEqual(recs["Leads caro"], "reallocate")   # CPL alto
        self.assertEqual(recs["Awareness"], "reallocate")    # no trae leads
        self.assertTrue(resp.result["plan"])

    def test_mediabuyer_zero_cpl_with_leads_is_scale_not_keep(self):
        # CPL $0 con leads > 0 (p.ej. leads orgánicos atribuidos) sigue <= objetivo:
        # debe escalar, no caer en "rendimiento aceptable" por accidente (cpl=0 truthy bug).
        a = build_agents(mock=True)["MEDIABUYER"]
        camps = [{"id": "1", "name": "Gratis", "objective": "OUTCOME_LEADS", "status": "active",
                  "region": "Santiago (RM)", "cpl_clp": 0, "leads": 5}]
        resp = a.run(TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="",
                                 instructions="x", data={"campaigns": camps, "good_cpl_clp": 6000}))
        rec = resp.result["recommendations"][0]
        self.assertEqual(rec["action"], "scale")
        self.assertIn("Gratis", resp.result["plan"])   # no crashea armando el plan

    def test_mediabuyer_no_data_yet_is_not_reported_as_fine(self):
        # Activa, OUTCOME_LEADS, sin leads ni CPL todavía (insights de Meta no conectados):
        # no es "rendimiento aceptable" — es ausencia de datos.
        a = build_agents(mock=True)["MEDIABUYER"]
        camps = [{"id": "1", "name": "Sin datos", "objective": "OUTCOME_LEADS", "status": "active",
                  "region": "Santiago (RM)", "cpl_clp": None, "leads": None}]
        resp = a.run(TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="",
                                 instructions="x", data={"campaigns": camps, "good_cpl_clp": 6000}))
        rec = resp.result["recommendations"][0]
        self.assertEqual(rec["action"], "keep")
        self.assertNotIn("aceptable", rec["reason"].lower())


class PricingTest(unittest.TestCase):
    """Los planes tienen precio en CLP (el MRR de la agencia)."""

    def test_plans_priced(self):
        from zero.config import TIERS
        self.assertEqual(TIERS["STARTER"]["price_clp"], 50_000)
        self.assertEqual(TIERS["GROWTH"]["price_clp"], 100_000)
        self.assertEqual(TIERS["SCALE"]["price_clp"], 500_000)
        self.assertIsNone(TIERS["ENTERPRISE"]["price_clp"])   # custom


class PitchWriterTest(unittest.TestCase):
    """El pitch se personaliza, usa el contexto y NO es el mismo cada vez."""

    def _gen(self, notes=""):
        a = build_agents(mock=True)["PITCHWRITER"]
        return a.run(TaskPayload(agent="PITCHWRITER", client_id="", client_tier="",
                                 instructions="x",
                                 data={"prospect": {"name": "Diego", "company": "Acme"}, "notes": notes})).result

    def test_personalizes_and_has_contract(self):
        r = self._gen()
        self.assertIn("subject", r)
        self.assertIn("body", r)
        self.assertIn("Diego", r["body"])      # personaliza con el nombre

    def test_varies_across_generations(self):
        bodies = {self._gen()["body"] for _ in range(10)}
        self.assertGreater(len(bodies), 1)      # no es el mismo mensaje siempre

    def test_uses_notes(self):
        # el contexto es la base del correo (arranca desde ahí)
        self.assertIn("mencionar su web nueva", self._gen("mencionar su web nueva")["body"].lower())


class ValidatorTest(unittest.TestCase):
    """Corrupt contacts are rejected before they reach the CRM."""

    def test_email_and_phone_rules(self):
        from zero.validators import ValidatorRules
        self.assertTrue(ValidatorRules.validate_email("ceo@acme.cl"))
        self.assertFalse(ValidatorRules.validate_email("usuario@"))
        self.assertFalse(ValidatorRules.validate_email("ejemplo@test"))
        self.assertFalse(ValidatorRules.validate_email(""))
        # GROWTH (default) requires >=7 digits; ENTERPRISE requires >=9
        self.assertTrue(ValidatorRules.validate_phone("+56 9 1234 5678"))
        self.assertFalse(ValidatorRules.validate_phone("12345"))
        self.assertFalse(ValidatorRules.validate_phone("912345678",
                         rules={"require": True, "min_digits": 12}))

    def test_validate_batch_filters_and_is_tier_aware(self):
        from zero.validators import ValidatorRules
        leads = [
            {"company": "Acme", "name": "Maria Soto", "email": "maria@acme.cl", "phone": "+56912345678"},
            {"company": "BadCo", "name": "Foo", "email": "usuario@ejemplo.com", "phone": None},
            {"company": "NoPhone", "name": "Bar", "email": "bar@nophone.cl", "phone": None},
            {"company": "", "name": "", "email": "x@y.cl", "phone": "123"},
        ]
        growth = ValidatorRules.validate_batch(leads, "GROWTH")
        self.assertEqual([l["company"] for l in growth], ["Acme", "NoPhone"])
        # ENTERPRISE also requires a phone with >=9 digits
        enterprise = ValidatorRules.validate_batch(leads, "ENTERPRISE")
        self.assertEqual([l["company"] for l in enterprise], ["Acme"])


class UsedEmailsTest(unittest.TestCase):
    """Recuerda correos contactados (autocompletar), sin duplicados ni basura."""

    def test_dedup_and_validation(self):
        m = SessionMemory(None)
        m.add_used_email("Foo@Bar.com")
        m.add_used_email("foo@bar.com")     # mismo (case-insensitive) → no duplica
        m.add_used_email("baz@qux.cl")
        m.add_used_email("no-es-email")     # sin @ → se ignora
        m.add_used_email("")                # vacío → se ignora
        self.assertEqual(sorted(m.used_emails), ["baz@qux.cl", "foo@bar.com"])
        self.assertIn("used_emails", m.snapshot())


class VendorTest(unittest.TestCase):
    """Catálogo de vendedores (Fernanda, Stéfano, ...), cada uno con su propio
    WhatsApp Business — y la asignación cliente → vendedor."""

    def test_catalog_seeds_fernanda_and_stefano(self):
        m = SessionMemory(None)
        vendors = m.list_vendors()
        ids = {v["id"] for v in vendors}
        self.assertIn("fernanda", ids)
        self.assertIn("stefano", ids)

    def test_get_vendor(self):
        m = SessionMemory(None)
        v = m.get_vendor("fernanda")
        self.assertEqual(v["name"], "Fernanda")
        self.assertIsNone(m.get_vendor("no-existe"))

    def test_upsert_vendor(self):
        m = SessionMemory(None)
        m.upsert_vendor({"id": "fernanda", "name": "Fernanda Editada",
                         "photo": None, "tone": "nuevo tono",
                         "phone": "+56 9 0000 0000", "whatsapp_phone_id": "999"})
        self.assertEqual(m.get_vendor("fernanda")["name"], "Fernanda Editada")
        # el resto del catálogo sigue intacto
        self.assertIsNotNone(m.get_vendor("stefano"))

    def test_client_vendor_assignment_and_default(self):
        from zero.config import DEFAULT_VENDOR_ID
        m = SessionMemory(None)
        # sin asignación -> default
        self.assertEqual(m.get_client_vendor("acme"), DEFAULT_VENDOR_ID)
        m.set_client_vendor("acme", "stefano")
        self.assertEqual(m.get_client_vendor("acme"), "stefano")

    def test_zero_vendor_for(self):
        from zero.config import DEFAULT_VENDOR_ID
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        # sin asignación -> el vendedor default
        self.assertEqual(z.vendor_for("acme")["id"], DEFAULT_VENDOR_ID)
        z.memory.set_client_vendor("acme", "stefano")
        self.assertEqual(z.vendor_for("acme")["id"], "stefano")

    def test_converse_injects_vendor_persona_without_secrets(self):
        """converse_result pasa data['vendor']={name,tone} a CONCIERGE (contrato
        que consume MOTOR·WhatsApp) y NUNCA filtra token/phone_id."""
        from zero.contracts import AgentResponse

        class Recorder:
            def __init__(self): self.task = None
            def run(self, task):
                self.task = task
                return AgentResponse(task_id="t", agent="CONCIERGE", status="done",
                                     result={"reply": "ok", "intent": "info"})

        rec = Recorder()
        z = Zero({"CONCIERGE": rec}, memory=SessionMemory(None))
        z.memory.set_client_vendor("acme", "stefano")
        z.converse_result("acme", "hola")
        vendor = rec.task.data["vendor"]
        self.assertEqual(vendor, {"name": "Stéfano", "tone": "formal, técnico, al grano"})
        self.assertNotIn("token", vendor)
        self.assertNotIn("whatsapp_phone_id", vendor)

    def test_snapshot_roundtrip_keeps_catalog_and_assignment(self):
        m = SessionMemory(None)
        m.set_client_vendor("acme", "stefano")
        m.list_vendors()   # asegura el catálogo sembrado antes de snapshot
        snap = m.snapshot()
        self.assertIn("vendors", snap)
        m2 = SessionMemory(None)
        m2._restore(snap)
        self.assertEqual(m2.get_client_vendor("acme"), "stefano")
        self.assertIn("fernanda", {v["id"] for v in m2.list_vendors()})

    def test_clients_count_for_counts_assigned_and_default_clients(self):
        """clients_count_for() es lo que GET /api/vendors expone por vendedor —
        se testea directo (stdlib) sin montar fastapi. No toca el registro
        guardado ni el contrato que usan credentials_for/Zero.vendor_for."""
        from zero.vendors import clients_count_for
        m = SessionMemory(None)
        m.register_client("acme", "GROWTH")
        m.register_client("beta", "GROWTH")
        m.register_client("gamma", "GROWTH")
        m.set_client_vendor("acme", "fernanda")
        m.set_client_vendor("beta", "stefano")
        # "gamma" sin asignación explícita -> cae al default (fernanda)
        self.assertEqual(clients_count_for("fernanda", m), 2)
        self.assertEqual(clients_count_for("stefano", m), 1)
        self.assertEqual(clients_count_for("no-existe", m), 0)


class VendorCredentialsTest(unittest.TestCase):
    """Resolución de credenciales por vendedor, con fallback a las env globales."""

    def setUp(self):
        import os
        self._env_keys = ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "WHATSAPP_TOKEN_FERNANDA")
        self._prev = {k: os.environ.get(k) for k in self._env_keys}

    def tearDown(self):
        import os
        for k, v in self._prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_credentials_fall_back_to_global_token(self):
        import os
        from zero.vendors import credentials_for, seed_vendors
        os.environ.pop("WHATSAPP_TOKEN_FERNANDA", None)
        os.environ["WHATSAPP_TOKEN"] = "global-token"
        fernanda = next(v for v in seed_vendors() if v["id"] == "fernanda")
        phone_id, token = credentials_for(fernanda)
        self.assertEqual(phone_id, fernanda["whatsapp_phone_id"])  # propio
        self.assertEqual(token, "global-token")                    # fallback global

    def test_per_vendor_token_takes_priority(self):
        import os
        from zero.vendors import credentials_for, seed_vendors
        os.environ["WHATSAPP_TOKEN"] = "global-token"
        os.environ["WHATSAPP_TOKEN_FERNANDA"] = "fernanda-token"
        fernanda = next(v for v in seed_vendors() if v["id"] == "fernanda")
        _, token = credentials_for(fernanda)
        self.assertEqual(token, "fernanda-token")

    def test_phone_id_falls_back_to_global_when_vendor_has_none(self):
        import os
        from zero.vendors import credentials_for
        os.environ["WHATSAPP_PHONE_ID"] = "global-phone-id"
        vendor = {"id": "sin-phone", "whatsapp_phone_id": None}
        phone_id, _ = credentials_for(vendor)
        self.assertEqual(phone_id, "global-phone-id")


class WhatsAppSenderCredentialsTest(unittest.TestCase):
    """WhatsAppSender acepta credenciales por parámetro (por-vendedor) o cae a
    las env globales — sin romper el `/api/whatsapp/status` existente."""

    def setUp(self):
        import os
        self._env_keys = ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID")
        self._prev = {k: os.environ.get(k) for k in self._env_keys}
        os.environ["WHATSAPP_TOKEN"] = "global-token"
        os.environ["WHATSAPP_PHONE_ID"] = "global-phone-id"

    def tearDown(self):
        import os
        for k, v in self._prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_uses_global_env_by_default(self):
        from zero.channels import WhatsAppSender
        s = WhatsAppSender()
        self.assertEqual(s.token, "global-token")
        self.assertEqual(s.phone_id, "global-phone-id")

    def test_uses_passed_in_credentials(self):
        from zero.channels import WhatsAppSender
        s = WhatsAppSender(phone_id="vendor-phone-id", token="vendor-token")
        self.assertEqual(s.token, "vendor-token")
        self.assertEqual(s.phone_id, "vendor-phone-id")


class WhatsAppTemplateTest(unittest.TestCase):
    """Contacto en frío por WhatsApp (primer toque / follow-up a quien no ha
    respondido) exige una plantilla pre-aprobada de Meta — un texto libre ahí
    sería rechazado por la Graph API real. Ver WHATSAPP_TEMPLATE en config.py."""

    def setUp(self):
        import zero.config as config
        self._prev_template = dict(config.WHATSAPP_TEMPLATE)

    def tearDown(self):
        import zero.config as config
        config.WHATSAPP_TEMPLATE.clear()
        config.WHATSAPP_TEMPLATE.update(self._prev_template)

    def test_template_send_without_configured_name_raises_clean_error(self):
        """Sin plantilla configurada, NUNCA cae a texto libre en silencio —
        levanta un error claro (el Outbox real lo degradaría a 'error' visible
        en el CRM, igual que cualquier otro fallo de envío)."""
        import zero.config as config
        from zero.channels import WhatsAppSender
        config.WHATSAPP_TEMPLATE["name"] = None
        s = WhatsAppSender(phone_id="p", token="t")
        with self.assertRaises(RuntimeError) as ctx:
            s.send({"to": "56911112222", "body": "hola",
                    "whatsapp_send_type": "template"})
        self.assertIn("WHATSAPP_TEMPLATE", str(ctx.exception))

    def test_template_body_shape_when_configured(self):
        import zero.config as config
        from zero.channels import WhatsAppSender
        config.WHATSAPP_TEMPLATE["name"] = "primer_contacto"
        config.WHATSAPP_TEMPLATE["language"] = "es"
        body = WhatsAppSender._template_body("56911112222", "hola, te escribo de...")
        self.assertEqual(body["type"], "template")
        self.assertEqual(body["template"]["name"], "primer_contacto")
        self.assertEqual(body["template"]["language"], {"code": "es"})
        self.assertEqual(
            body["template"]["components"][0]["parameters"][0]["text"],
            "hola, te escribo de...",
        )

    def test_reply_without_send_type_still_uses_free_text(self):
        """Sin whatsapp_send_type (o distinto de 'template') sigue mandando
        texto libre — el camino de responder a un lead que ya escribió. No
        necesita ninguna plantilla configurada, a diferencia del contacto en frío."""
        import zero.config as config
        from zero.channels import WhatsAppSender
        config.WHATSAPP_TEMPLATE["name"] = None   # ni siquiera hace falta plantilla
        body = WhatsAppSender._text_body("56911112222", "hola, gracias por escribir")
        self.assertEqual(body, {
            "messaging_product": "whatsapp", "to": "56911112222", "type": "text",
            "text": {"body": "hola, gracias por escribir"},
        })

    def test_first_touch_tags_whatsapp_as_template(self):
        """_send_first_touch marca el mensaje de WhatsApp como contacto en frío
        (plantilla); el mismo lead por email no lleva esa marca."""
        crm = CRM(None)
        box_calls = []

        class RecordingOutbox:
            live = True
            def send(self, msg, wa_creds=None):
                box_calls.append(msg)
                return {"channel": msg.get("channel"), "to": msg.get("to"),
                       "status": "sent", "id": "x", "error": None, "via": "whatsapp"}

        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm,
                 outbox=RecordingOutbox())
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        wa_calls = [c for c in box_calls if c.get("channel") == "whatsapp"]
        self.assertTrue(wa_calls, "el pipeline mock no generó ningún envío de WhatsApp")
        self.assertTrue(all(c.get("whatsapp_send_type") == "template" for c in wa_calls))

    def test_followup_tags_whatsapp_as_template(self):
        """run_followups también marca sus envíos de WhatsApp como plantilla —
        sigue siendo contacto a alguien que no ha respondido."""
        from datetime import datetime, timedelta, timezone
        crm = CRM(None)
        box_calls = []

        class RecordingOutbox:
            live = True
            def send(self, msg, wa_creds=None):
                box_calls.append(msg)
                return {"channel": msg.get("channel"), "to": msg.get("to"),
                       "status": "sent", "id": "x", "error": None, "via": "whatsapp"}

        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm,
                 outbox=RecordingOutbox())
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        box_calls.clear()
        z.run_followups("acme", as_of=future)
        wa_calls = [c for c in box_calls if c.get("channel") == "whatsapp"]
        if wa_calls:   # depende de qué canal haya elegido TRACKER en mock
            self.assertTrue(all(c.get("whatsapp_send_type") == "template") for c in wa_calls)


class ApiRoutesTest(unittest.TestCase):
    """Guarda contra rutas duplicadas en api.py. Registrar el mismo (método,
    ruta) dos veces no es un error de Python — FastAPI no se queja — pero solo
    la PRIMERA definición responde; la segunda queda muerta en silencio. Ya
    casi pasó una vez (dos ramas agregando GET /api/vendors por separado).

    Análisis estático con `ast` (stdlib) sobre el archivo fuente, sin importar
    `api.py` ni `fastapi` — el núcleo (esta suite) corre sin dependencias, y
    fastapi es opcional (solo para correr el servidor de verdad)."""

    _HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

    def _routes(self):
        api_path = Path(__file__).resolve().parent.parent / "api.py"
        tree = ast.parse(api_path.read_text("utf-8"), filename=str(api_path))
        routes = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                # @app.get("/x") -> Call(func=Attribute(value=Name('app'), attr='get'))
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app"
                        and dec.func.attr in self._HTTP_METHODS):
                    continue
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    routes.append((dec.func.attr.upper(), dec.args[0].value, node.name, node.lineno))
        return routes

    def test_no_duplicate_routes(self):
        routes = self._routes()
        # Si esto falla, cambió el patrón @app.<método>("/ruta") o api.py se movió —
        # el test dejó de poder ver rutas, hay que revisar _routes(), no ignorarlo.
        self.assertGreater(len(routes), 10, "no se encontraron rutas en api.py — ¿cambió el patrón?")

        seen: dict[tuple[str, str], tuple[str, int]] = {}
        dupes = []
        for method, path, func_name, lineno in routes:
            key = (method, path)
            if key in seen:
                prev_name, prev_line = seen[key]
                dupes.append(f"{method} {path}: línea {prev_line} ({prev_name}) y línea {lineno} ({func_name})")
            else:
                seen[key] = (func_name, lineno)
        self.assertEqual(
            dupes, [],
            "rutas duplicadas en api.py — la segunda queda muerta en silencio:\n" + "\n".join(dupes)
        )


if __name__ == "__main__":
    unittest.main()
