import unittest
from candyconc.domain.query_parser import parse_query, And, Or, Not, Near, Attr, Term


class TestStructuredQuery(unittest.TestCase):
    def test_nested_boolean_with_attr(self):
        q = "([pos=ADJ] OR cat) AND NOT ([lemma=go] NEAR/2 [pos=VERB])"
        node = parse_query(q)
        self.assertIsInstance(node, And)
        self.assertIsInstance(node.left, Or)
        self.assertIsInstance(node.right, Not)
        left = node.left
        self.assertIsInstance(left.left, Attr)
        self.assertEqual(left.left.key, "pos")
        self.assertEqual(left.left.value, "ADJ")
        self.assertIsInstance(left.right, Term)
        self.assertEqual(left.right.value, "cat")
        neg = node.right.node
        self.assertIsInstance(neg, Near)
        self.assertEqual(neg.distance, 2)
        self.assertIsInstance(neg.left, Attr)
        self.assertEqual(neg.left.key, "lemma")
        self.assertEqual(neg.left.value, "go")
        self.assertIsInstance(neg.right, Attr)
        self.assertEqual(neg.right.key, "pos")
        self.assertEqual(neg.right.value, "VERB")

    def test_or_with_multiple_near(self):
        q = "(dog NEAR/1 cat) OR ([lemma=see] NEAR/3 [pos=NOUN])"
        node = parse_query(q)
        self.assertIsInstance(node, Or)
        left = node.left
        right = node.right
        self.assertIsInstance(left, Near)
        self.assertEqual(left.distance, 1)
        self.assertIsInstance(left.left, Term)
        self.assertIsInstance(left.right, Term)
        self.assertEqual(left.left.value, "dog")
        self.assertEqual(left.right.value, "cat")
        self.assertIsInstance(right, Near)
        self.assertEqual(right.distance, 3)
        self.assertIsInstance(right.left, Attr)
        self.assertEqual(right.left.key, "lemma")
        self.assertEqual(right.left.value, "see")
        self.assertIsInstance(right.right, Attr)
        self.assertEqual(right.right.key, "pos")
        self.assertEqual(right.right.value, "NOUN")

    def test_quoted_terms_and_attrs(self):
        q = '"New York" NEAR/3 [pos=NOUN]'
        node = parse_query(q)
        self.assertIsInstance(node, Near)
        self.assertEqual(node.distance, 3)
        self.assertIsInstance(node.left, Term)
        self.assertEqual(node.left.value, "New York")
        self.assertIsInstance(node.right, Attr)
        self.assertEqual(node.right.key, "pos")
        self.assertEqual(node.right.value, "NOUN")

    def test_quoted_attr_value(self):
        q = '[lemma="go fish"] AND [pos=VERB]'
        node = parse_query(q)
        self.assertIsInstance(node, And)
        self.assertIsInstance(node.left, Attr)
        self.assertEqual(node.left.key, "lemma")
        self.assertEqual(node.left.value, "go fish")
        self.assertIsInstance(node.right, Attr)
        self.assertEqual(node.right.key, "pos")
        self.assertEqual(node.right.value, "VERB")


if __name__ == "__main__":
    unittest.main()
