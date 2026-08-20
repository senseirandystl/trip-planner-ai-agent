import json
import unittest

from src.validation import (
    extract_json,
    itinerary_poi_ids,
    other_days_unchanged,
    validate_itinerary_poi_ids,
    validate_user_inputs,
)


class ValidationTests(unittest.TestCase):
    def test_user_inputs(self):
        self.assertTrue(validate_user_inputs("", 3, "moderate", ["food"]))
        self.assertFalse(validate_user_inputs("Kyoto", 3, "moderate", ["food"]))

    def test_extract_json_from_fence(self):
        raw = "Here you go\n```json\n{\"destination\": \"Kyoto\", \"days\": []}\n```"
        self.assertEqual(extract_json(raw)["destination"], "Kyoto")

    def test_poi_validation(self):
        itin = {
            "days": [
                {
                    "day": 1,
                    "morning": [{"poi_id": "osm_node_1", "name": "A"}],
                    "afternoon": [],
                    "evening": [],
                }
            ]
        }
        validate_itinerary_poi_ids(itin, {"osm_node_1": {"name": "A"}})
        with self.assertRaises(ValueError):
            validate_itinerary_poi_ids(itin, {"osm_node_2": {"name": "B"}})
        self.assertEqual(itinerary_poi_ids(itin), ["osm_node_1"])

    def test_single_day_guard(self):
        day = {
            "day": 1,
            "morning": [{"poi_id": "a"}],
            "afternoon": [],
            "evening": [],
        }
        original = {"days": [day, {"day": 2, "morning": [{"poi_id": "b"}], "afternoon": [], "evening": []}]}
        refined = json.loads(json.dumps(original))
        refined["days"][0]["morning"] = [{"poi_id": "c"}]
        other_days_unchanged(original, refined, 1)
        refined["days"][1]["morning"] = [{"poi_id": "z"}]
        with self.assertRaises(ValueError):
            other_days_unchanged(original, refined, 1)


if __name__ == "__main__":
    unittest.main()
