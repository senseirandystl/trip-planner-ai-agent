import unittest

from src.geocoding import city_key
from src.pois import build_overpass_query, tags_for_interests


class PoiHelperTests(unittest.TestCase):
    def test_city_key(self):
        self.assertEqual(city_key("  Santa   Fe, NM "), "santa fe, nm")

    def test_interest_tags(self):
        tags = tags_for_interests(["food", "outdoors"])
        keys = {k for k, _ in tags}
        self.assertIn("amenity", keys)
        self.assertTrue({"leisure", "natural", "tourism"} & keys)

    def test_overpass_query_contains_regex(self):
        q = build_overpass_query(35.68, -105.93, [("amenity", "restaurant|cafe")], limit=20)
        self.assertIn("restaurant|cafe", q)
        self.assertIn("around:8000,35.68,-105.93", q)
        self.assertIn("[out:json]", q)


if __name__ == "__main__":
    unittest.main()
