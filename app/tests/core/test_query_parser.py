import unittest
from candyconc.domain.query_parser import parse_query, Term, And, Or, Near


class TestQueryParser(unittest.TestCase):
    def test_simple_boolean(self):
        node = parse_query("dog AND cat OR mouse")
        self.assertIsInstance(node, Or)
        self.assertIsInstance(node.left, And)
        self.assertIsInstance(node.right, Term)
        self.assertEqual(node.left.left.value, "dog")
        self.assertEqual(node.left.right.value, "cat")
        self.assertEqual(node.right.value, "mouse")

    def test_grouping_near(self):
        node = parse_query("(dog OR cat) NEAR/2 mouse")
        self.assertIsInstance(node, Near)
        self.assertEqual(node.distance, 2)
        self.assertIsInstance(node.left, Or)
        self.assertIsInstance(node.right, Term)
        self.assertEqual(node.right.value, "mouse")
        left = node.left
        self.assertEqual(left.left.value, "dog")
        self.assertEqual(left.right.value, "cat")


if __name__ == "__main__":
    unittest.main()
