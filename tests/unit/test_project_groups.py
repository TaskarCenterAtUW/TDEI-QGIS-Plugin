# -*- coding: utf-8 -*-
import base64
import json
import os
import sys
import unittest

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from tdei.api.v1.project_groups import parse_project_groups  # noqa: E402
from tdei.auth.jwt_util import (  # noqa: E402
    decode_jwt_payload,
    is_tdei_admin,
    jwt_realm_roles,
    jwt_sub,
)
from tdei.core.models import DatasetScope  # noqa: E402
from tdei.features.datasets.service import DatasetService  # noqa: E402


def _make_jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = (
        base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
        .decode()
        .rstrip("=")
    )
    return "{}.{}.sig".format(header, body)


class FakeSettings:
    def get(self, key, default=None):
        return default


class JwtUtilTests(unittest.TestCase):
    def test_reads_sub(self):
        token = _make_jwt({"sub": "user-uuid-123", "email": "a@b.com"})
        self.assertEqual(jwt_sub(token), "user-uuid-123")
        self.assertEqual(decode_jwt_payload(token)["sub"], "user-uuid-123")

    def test_missing_sub(self):
        token = _make_jwt({"email": "a@b.com"})
        self.assertEqual(jwt_sub(token), "")

    def test_tdei_admin_realm_role(self):
        token = _make_jwt(
            {
                "sub": "admin-1",
                "realm_access": {"roles": ["tdei-admin", "offline_access"]},
            }
        )
        self.assertEqual(jwt_realm_roles(token), ["tdei-admin", "offline_access"])
        self.assertTrue(is_tdei_admin(token))

    def test_non_admin_realm_role(self):
        token = _make_jwt({"realm_access": {"roles": ["user"]}})
        self.assertFalse(is_tdei_admin(token))
        self.assertFalse(is_tdei_admin(""))


class ProjectGroupParseTests(unittest.TestCase):
    def test_parses_name_and_dedupes(self):
        groups = parse_project_groups(
            [
                {
                    "tdei_project_group_id": "pg-1",
                    "project_group_name": "Alpha",
                    "roles": ["poc"],
                },
                {
                    "tdei_project_group_id": "pg-1",
                    "project_group_name": "Alpha again",
                },
            ]
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].id, "pg-1")
        self.assertEqual(groups[0].name, "Alpha")
        self.assertEqual(groups[0].roles, ["poc"])


class DatasetListParamsTests(unittest.TestCase):
    def setUp(self):
        self.svc = DatasetService(
            api_client=None,
            layer_manager=None,
            settings=FakeSettings(),
        )

    def test_my_project_groups_scope(self):
        params = self.svc._build_list_params(
            name="roads",
            dataset_id="",
            scope=DatasetScope.MY_PROJECT_GROUPS,
            project_group_id=None,
            page_no=1,
            page_size=10,
        )
        self.assertEqual(params["name"], "roads")
        self.assertTrue(params["include_my_groups"])
        self.assertNotIn("tdei_project_group_id", params)
        self.assertEqual(params["page_no"], 1)
        self.assertEqual(params["page_size"], 10)

    def test_specific_project_group(self):
        params = self.svc._build_list_params(
            name="",
            dataset_id="ds-1",
            scope=DatasetScope.CURRENT_PROJECT_GROUP,
            project_group_id="pg-9",
            page_no=2,
            page_size=10,
        )
        self.assertEqual(params["tdei_dataset_id"], "ds-1")
        self.assertEqual(params["tdei_project_group_id"], "pg-9")
        self.assertNotIn("include_my_groups", params)
        self.assertEqual(params["page_no"], 2)

    def test_all_scope_omits_group_filters(self):
        params = self.svc._build_list_params(
            name="",
            dataset_id="",
            scope=DatasetScope.ALL,
            project_group_id=None,
            page_no=1,
            page_size=10,
        )
        self.assertNotIn("include_my_groups", params)
        self.assertNotIn("tdei_project_group_id", params)


if __name__ == "__main__":
    unittest.main()
