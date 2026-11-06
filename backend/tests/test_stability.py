import unittest

from app.vector_compat import dimensions_compatible, mismatch_message
from app.ingest import chunk_id


class VectorCompatibilityTests(unittest.TestCase):
    def test_empty_collection_accepts_first_dimension(self):
        self.assertTrue(dimensions_compatible(None, 256))

    def test_equal_dimensions_are_compatible(self):
        self.assertTrue(dimensions_compatible(4096, 4096))

    def test_changed_model_is_detected(self):
        self.assertFalse(dimensions_compatible(4096, 256))
        message = mismatch_message(4096, 256)
        self.assertIn("4096", message)
        self.assertIn("256", message)
        self.assertIn("关键词检索", message)

    def test_chunk_ids_are_namespaced_by_knowledge_base(self):
        left = chunk_id("kb_a", "samehash", 0)
        right = chunk_id("kb_b", "samehash", 0)
        self.assertNotEqual(left, right)
        self.assertEqual(left, "kb_a_samehash_0")


if __name__ == "__main__":
    unittest.main()
