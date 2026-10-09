import tempfile
import unittest
from pathlib import Path

from rag.chunker import chunk_document
from rag.documents import load_directory, parse_document
from rag.retriever import NO_POLICY, Retriever
from rag.service import PolicyService
from rag.store import PolicyStore
from tests.fixtures import POLICY_DIR


def service() -> PolicyService:
    s = PolicyService(None)
    s.ingest_directory(POLICY_DIR)
    return s


class DocumentsAndChunking(unittest.TestCase):
    def test_front_matter(self):
        docs = {d.policy_id: d for d in load_directory(POLICY_DIR)}
        self.assertEqual(set(docs), {"HR-WT-001", "HR-OT-002", "OPS-SUP-007"})
        self.assertEqual(docs["HR-WT-001"].version, "3.1")
        self.assertEqual(docs["HR-WT-001"].metadata["owner"], "Human Resources")
        self.assertTrue(docs["HR-WT-001"].content_sha256)

    def test_sections_become_citable_chunks(self):
        doc = load_directory(POLICY_DIR)[0]
        chunks = {c.section: c for c in chunk_document(doc)}
        self.assertIn("3.1", chunks)
        self.assertEqual(chunks["3.1"].chunk_id, "HR-WT-001#3.1")
        self.assertIn("Rest and recovery > 3.1 Rest between shifts", chunks["3.1"].heading_path)
        self.assertIn("11 hours of rest", chunks["3.1"].text)

    def test_long_sections_split_on_sentences(self):
        body = " ".join(f"Rule number {i} says employees must do thing {i}." for i in range(60))
        doc = parse_document(f"# Big\n## 1. Rules\n{body}", "BIG")
        chunks = chunk_document(doc, max_words=100)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(len({c.chunk_id for c in chunks}), len(chunks))
        self.assertTrue(all(c.section == "1" for c in chunks))

    def test_no_front_matter_defaults(self):
        doc = parse_document("# Leave Rules\nText.", "LEAVE-RULES")
        self.assertEqual((doc.policy_id, doc.title), ("LEAVE-RULES", "Leave Rules"))


class Retrieval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = service()

    def top(self, q):
        r = self.svc.lookup(q)
        return r.hits[0] if r.hits else None

    def test_finds_the_right_section(self):
        cases = {
            "how much rest do we need between shifts": "HR-WT-001#3.1",
            "what is the overtime limit": "HR-OT-002#2",
            "does overtime need approval": "HR-OT-002#1",
            "can L2 agents work 45 hours a week": "OPS-SUP-007#3",
            "how many weekends can someone work": "HR-WT-001#4",
            "who can cover the L2 queue": "OPS-SUP-007#1.1",
            "how often can an agent's schedule be changed": "OPS-SUP-007#4",
        }
        for q, expected in cases.items():
            hit = self.top(q)
            self.assertIsNotNone(hit, q)
            self.assertEqual(hit.chunk.chunk_id, expected, q)

    def test_every_hit_is_grounded(self):
        hit = self.top("how much rest between shifts")
        self.assertEqual(hit.policy_id, "HR-WT-001")
        self.assertEqual(hit.chunk.section, "3.1")
        self.assertGreater(hit.confidence, 0.5)
        self.assertIn("rest", hit.matched_terms)
        self.assertEqual(hit.citation(), "Working Time Policy §3.1 (HR-WT-001)")

    def test_no_applicable_policy(self):
        for q in ("is there a dress code", "parking reimbursement", "what's the wifi password", ""):
            r = self.svc.lookup(q)
            self.assertEqual(r.status, "no_applicable_policy", q)
            self.assertEqual(r.message, NO_POLICY)
            self.assertEqual(r.hits, [])

    def test_policy_filter(self):
        r = Retriever(self.svc.store).search("hours", policy_ids={"HR-OT-002"}, min_confidence=0.0)
        self.assertTrue(all(h.policy_id == "HR-OT-002" for h in r.hits))


class StoreLifecycle(unittest.TestCase):
    def test_new_version_replaces_old(self):
        store = PolicyStore()
        store.add_document(parse_document("# P\n## 1. Rest\nAt least 11 hours of rest between shifts.", "P-1"))
        store.add_document(parse_document("# P\n## 1. Rest\nAt least 12 hours of rest between shifts.", "P-1"))
        self.assertEqual(len(store), 1)
        self.assertIn("12 hours", store.chunks[0].text)

    def test_save_and_load(self):
        svc = service()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "store.json"
            svc.store.save(path)
            loaded = PolicyStore.load(path)
        self.assertEqual([c.chunk_id for c in loaded.chunks], [c.chunk_id for c in svc.store.chunks])
        self.assertEqual(Retriever(loaded).search("rest between shifts").hits[0].chunk.chunk_id, "HR-WT-001#3.1")

    def test_empty_store(self):
        r = Retriever(PolicyStore()).search("rest")
        self.assertEqual(r.status, "no_applicable_policy")


if __name__ == "__main__":
    unittest.main()
