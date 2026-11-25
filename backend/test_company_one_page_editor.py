"""Isolated contract tests for the one-save company editor without live DB dependencies."""
import ast
import base64
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from fastapi import HTTPException
from pydantic import BaseModel, Field
try:
    from backend_source import read_backend_source  # the backend code lives in app/features/*.py
except ImportError:  # started as `python -m unittest backend.test_...` from the repository root
    from .backend_source import read_backend_source

SOURCE = Path(__file__).parent / 'app' / 'features' / 'admin_records.py'  # shown in tracebacks only


AUDIT_CALLS = []


class Company:
    pass


class AppSetting:
    def __init__(self, key, value):
        self.key = key
        self.value = value


class FakeDB:
    def __init__(self):
        self.company = SimpleNamespace(id=7, name='Old Company')
        self.settings = {}
        self.commits = 0

    def get(self, model, key):
        return self.company if model is Company and key == 7 else self.settings.get(key) if model is AppSetting else None

    def add(self, item):
        if isinstance(item, AppSetting):
            self.settings[item.key] = item

    def commit(self):
        self.commits += 1

    def refresh(self, item):
        pass


def load_edited_endpoints():
    tree = ast.parse(read_backend_source())
    required = {'_validate_company_driver_logo', 'CompanyEdit', 'edit_company'}
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in required:
            node.decorator_list = []
            selected.append(node)
    if {node.name for node in selected} != required:
        raise AssertionError('Required company edit endpoint nodes missing')
    env = {'BaseModel': BaseModel, 'Field': Field, 'HTTPException': HTTPException,
           'Depends': lambda _: None, 'get_db': None, 'current_user': None,
           'Session': object, 'User': object, 'CompanyOut': object, 'Company': Company,
           # edit_company writes a security audit row; here it only records the call, as `allow` is replaced too
           'audit': lambda db, action, **kwargs: AUDIT_CALLS.append(action),
           'AppSetting': AppSetting, 'json': json,
           '_company_logo_setting': lambda cid: f'logo:{cid}',
           'allow': lambda user, *roles: None if user.role in roles else (_ for _ in ()).throw(HTTPException(403)),
           '__name__': '__isolated_company_editor__'}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec'), env)
    return env


class CompanyEditorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = load_edited_endpoints()

    def setUp(self):
        self.db = FakeDB()
        self.admin = SimpleNamespace(role='super_admin')
        AUDIT_CALLS.clear()

    def update(self, **data):
        return self.env['edit_company'](7, self.env['CompanyEdit'](**data), self.db, self.admin)

    def test_legacy_name_only_patch_unchanged(self):
        self.update(name='Updated Company')
        self.assertEqual(self.db.company.name, 'Updated Company')
        self.assertEqual(self.db.commits, 1)
        self.assertFalse(self.db.settings)

    def test_edit_is_audited_in_the_same_transaction(self):
        self.update(name='Updated Company')
        self.assertEqual(AUDIT_CALLS, ['company.update'])
        self.assertEqual(self.db.commits, 1, 'the audit row must ride on the edit\'s own commit')

    def test_name_and_logo_written_in_one_commit(self):
        value = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'dummy-payload').decode()
        self.update(name='Updated Company', logo_data=value)
        self.assertEqual(self.db.company.name, 'Updated Company')
        self.assertEqual(json.loads(self.db.settings['logo:7'].value), {'logo_data': value})
        self.assertEqual(self.db.commits, 1)

    def test_clear_logo_and_rename_in_one_commit(self):
        self.db.settings['logo:7'] = AppSetting('logo:7', json.dumps({'logo_data': 'previous'}))
        self.update(name='Updated Company', logo_data='')
        self.assertEqual(json.loads(self.db.settings['logo:7'].value)['logo_data'], '')
        self.assertEqual(self.db.commits, 1)

    def test_invalid_logo_rejected_before_mutations(self):
        for logo in ['not an image', 'data:image/png;base64,!!!!',
                     'data:image/jpeg;base64,' + base64.b64encode(b'Not a JPEG').decode()]:
            with self.subTest(logo=logo[:20]):
                with self.assertRaises(HTTPException):
                    self.update(name='Different Name', logo_data=logo)
                self.assertEqual(self.db.company.name, 'Old Company')
                self.assertEqual(self.db.commits, 0)

    def test_company_admin_cannot_rename_company_or_upload_by_patch(self):
        with self.assertRaises(HTTPException) as raised:
            self.env['edit_company'](7, self.env['CompanyEdit'](name='Updated Company'), self.db,
                                     SimpleNamespace(role='company_admin'))
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(self.db.commits, 0)


if __name__ == '__main__':
    unittest.main()
