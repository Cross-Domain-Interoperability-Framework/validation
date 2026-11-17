"""Tests for the agent inside a schema:Role (FrameAndValidate).

schema.org's Role pattern repeats the property the Role sits under:
schema:contributor inside a contributor Role, schema:participant inside an
activity's participant Role. Both properties are in ARRAY_PROPERTIES, so the
normalizer wrapped the Role's single agent in an array, which AgentInRole
(a single Person / Organization / {@id}) rejects. Inside a Role a
one-element array is unwrapped; outside a Role the array stays.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from FrameAndValidate import remove_nulls_and_normalize

LAB = {"@id": "ex:laboratory01", "@type": ["schema:Organization"], "schema:name": "Lab"}


class RoleAgentUnwrap(unittest.TestCase):
    def test_participant_inside_role_is_unwrapped(self):
        out = remove_nulls_and_normalize({"schema:participant": [{
            "@type": ["schema:Role"], "schema:roleName": "Host",
            "schema:participant": LAB}]})
        self.assertEqual(out["schema:participant"][0]["schema:participant"], LAB)

    def test_contributor_inside_role_is_unwrapped(self):
        out = remove_nulls_and_normalize({"schema:contributor": [{
            "@type": ["schema:Role"], "schema:roleName": "PI",
            "schema:contributor": LAB}]})
        self.assertEqual(out["schema:contributor"][0]["schema:contributor"], LAB)

    def test_participant_outside_role_stays_an_array(self):
        out = remove_nulls_and_normalize({"@type": ["schema:Action"], "schema:participant": LAB})
        self.assertEqual(out["schema:participant"], [LAB])


if __name__ == "__main__":
    unittest.main()
