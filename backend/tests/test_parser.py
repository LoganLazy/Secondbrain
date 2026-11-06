import unittest
from unittest.mock import patch

from app import parser


class ChunkCompletenessTests(unittest.TestCase):
    def chunks(self, pages, size=50, overlap=10):
        with patch.object(parser.config, 'get', side_effect=lambda key: {
                'CHUNK_SIZE': size, 'CHUNK_OVERLAP': overlap}[key]):
            return parser.chunk_text(pages)

    def test_long_line_reconstructs_without_dropping_middle_or_tail(self):
        text = ''.join(chr(0x4e00 + i) for i in range(317))
        chunks = self.chunks([(text, 1)])
        reconstructed = chunks[0]['text'] + ''.join(chunk['text'][10:] for chunk in chunks[1:])
        self.assertEqual(reconstructed, text)
        self.assertTrue(all(len(chunk['text']) <= 50 for chunk in chunks))

    def test_overlap_never_contains_previous_page(self):
        chunks = self.chunks([('FIRST PAGE ' * 10, 2), ('SECOND PAGE ' * 10, 7)])
        self.assertTrue(any(chunk['page'] == 7 for chunk in chunks))
        self.assertTrue(all('FIRST' not in chunk['text'] for chunk in chunks if chunk['page'] == 7))
        self.assertTrue(all('SECOND' not in chunk['text'] for chunk in chunks if chunk['page'] == 2))

    def test_short_page_and_final_short_chunk_are_retained(self):
        chunks = self.chunks([('short', 3), ('x' * 51, 5)], overlap=0)
        self.assertEqual(chunks, [{'text': 'short', 'page': 3},
                                 {'text': 'x' * 50, 'page': 5}, {'text': 'x', 'page': 5}])

    def test_paragraphs_empty_pages_and_zero_overlap(self):
        chunks = self.chunks([(' \n', 1), ('  alpha\n\nbeta   \n gamma ', 4)], size=8, overlap=0)
        self.assertEqual(''.join(chunk['text'] for chunk in chunks), 'alpha beta gamma')
        self.assertTrue(all(chunk['page'] == 4 for chunk in chunks))

    def test_invalid_configuration_fails_instead_of_looping(self):
        for size, overlap in [(0, 0), (10, 10), (10, 11), (10, -1)]:
            with self.subTest(size=size, overlap=overlap), self.assertRaises(ValueError):
                self.chunks([('text', 1)], size, overlap)
