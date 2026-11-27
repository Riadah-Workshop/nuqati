"""Static security guards. They read the source only: no server, no database, no third-party packages.

They freeze what the Phase 2 review found to be correct, so a later change cannot quietly undo it:
  1. the exact list of routes that need no login,
  2. the exact places where SQL text is assembled dynamically,
  3. that sensitive handlers keep writing to the security audit trail, and never put secrets in it,
  4. that unsafe calls (eval, shell=True, ...) do not appear.

If one of these fails because you changed something on purpose, update the list in this file in the same
commit and say why in the commit message: that is the review step.
"""
import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parent / "app"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _modules():
    for path in sorted(APP.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        yield path.relative_to(APP).as_posix(), source, ast.parse(source)


def _routes():
    """Every `@app.<method>('<path>')` / `@router.<method>('<path>')` handler, including nested ones."""
    for rel, source, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute) and deco.func.attr in HTTP_METHODS
                        and deco.args and isinstance(deco.args[0], ast.Constant) and isinstance(deco.args[0].value, str)):
                    yield {
                        "file": rel, "method": deco.func.attr.upper(), "path": deco.args[0].value, "name": node.name,
                        "needs_login": "current_user" in ast.unparse(node.args),
                        "source": ast.get_source_segment(source, node) or "",
                    }


# Reviewed in Phase 2 (docs/compliance and the Phase 2 findings). Each of these is meant to work without a login:
# sign-in and recovery, the link-token flows, health checks, branding for the login page, the WhatsApp webhook
# (verified by its own signature) and the read-only live-share link (a random, expiring, revocable token).
PUBLIC_ROUTES = {
    ("features/auth_accounts.py", "POST", "/api/v1/auth/login"),
    ("features/mfa_accounts.py", "POST", "/api/v1/auth/login/mfa"),  # second step: needs the token of the password step
    ("features/auth_accounts.py", "POST", "/api/v1/auth/password-reset/request"),
    ("features/auth_accounts.py", "POST", "/api/v1/auth/password-reset/confirm"),
    ("features/auth_accounts.py", "POST", "/api/v1/auth/email-change/confirm"),
    ("features/auth_accounts.py", "POST", "/api/v1/auth/driver-phone-login"),
    ("features/auth_accounts.py", "POST", "/api/v1/auth/driver-iqama-login"),
    ("features/auth_accounts.py", "POST", "/api/v1/auth/driver-refresh"),
    ("features/branding.py", "GET", "/api/v1/public/branding"),
    ("features/branding.py", "GET", "/api/v1/public/label-defaults"),
    ("features/health.py", "GET", "/api/v1/health"),
    ("features/health.py", "GET", "/api/v1/ready"),
    ("features/invitations.py", "POST", "/api/v1/invitations/accept"),
    ("features/live_tracking.py", "GET", "/api/v1/public/live-share/{token}"),
    ("whatsapp.py", "GET", "/webhook"),
    ("whatsapp.py", "POST", "/webhook"),
}

# Public routes that take a secret or an identifier must be throttled.
THROTTLED_PUBLIC_HANDLERS = {
    "login", "request_dashboard_password_reset", "confirm_dashboard_password_reset", "confirm_dashboard_email_change",
    "driver_phone_login", "driver_iqama_login", "login_mfa",
}


def test_routes_without_login_are_exactly_the_reviewed_set():
    found = {(r["file"], r["method"], r["path"]) for r in _routes() if not r["needs_login"]}
    unexpected = sorted(found - PUBLIC_ROUTES)
    vanished = sorted(PUBLIC_ROUTES - found)
    assert not unexpected, (
        "New route(s) that do not require a login: " + str(unexpected) + ". Add `user: User = Depends(current_user)` "
        "or, if public access is intended, review it and add it to PUBLIC_ROUTES in this file.")
    assert not vanished, "Reviewed public route(s) no longer found (renamed or moved?): " + str(vanished)


def test_public_credential_routes_are_rate_limited():
    by_name = {r["name"]: r for r in _routes()}
    missing = sorted(n for n in THROTTLED_PUBLIC_HANDLERS if "enforce_auth_limit(" not in by_name[n]["source"])
    assert not missing, f"Public credential endpoints without enforce_auth_limit(): {missing}"


def test_api_docs_are_off_unless_explicitly_enabled():
    source = (APP / "api_app.py").read_text(encoding="utf-8")
    assert "NUQATI_ENABLE_API_DOCS" in source
    for argument in ("docs_url", "redoc_url", "openapi_url"):
        assert re.search(rf"{argument}\s*=\s*'/\w+(\.json)?'\s+if\s+_docs_enabled\s+else\s+None", source), (
            f"FastAPI(...) must set {argument} to None unless NUQATI_ENABLE_API_DOCS is set")
    for compose in ("compose.yml",):
        text = (APP.parent.parent / compose).read_text(encoding="utf-8")
        assert "NUQATI_ENABLE_API_DOCS" not in text, f"{compose} is the production file: API docs must stay off there"


# ---------------------------------------------------------------------------------------- dynamic SQL
# Interpolations into SQL text that were reviewed: each is built from fixed literals in the same function,
# never from request data. Values always travel as bound parameters (:name).
REVIEWED_SQL_INTERPOLATIONS = {
    "features/assistance.py": {"where"},
    "features/maintenance.py": {"where"},
    "features/mobile_audit.py": {"clause", "where"},
    "features/security_audit_log.py": {"where"},
    "features/trips.py": {"table"},
}
# SQL assembled by string concatenation (reviewed): file -> number of call sites.
REVIEWED_SQL_CONCATENATIONS = {"features/diagnostics.py": 1}


def _sql_call_sites():
    for rel, _source, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name in ("text", "execute", "exec_driver_sql"):
                yield rel, node.args[0]


def test_sql_text_is_only_assembled_in_reviewed_places():
    interpolated, concatenated = {}, {}
    for rel, arg in _sql_call_sites():
        if isinstance(arg, ast.JoinedStr):
            names = {ast.unparse(v.value) for v in arg.values if isinstance(v, ast.FormattedValue)}
            if names:
                interpolated.setdefault(rel, set()).update(names)
        elif isinstance(arg, ast.BinOp) or (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
                                            and arg.func.attr == "format"):
            concatenated[rel] = concatenated.get(rel, 0) + 1
    assert interpolated == REVIEWED_SQL_INTERPOLATIONS, (
        "SQL text with f-string interpolation changed. Use bound parameters (:name) for values; if a fragment must be "
        f"interpolated, build it only from literals and add it here after review.\nfound: {interpolated}")
    assert concatenated == REVIEWED_SQL_CONCATENATIONS, f"SQL built by concatenation/format() changed: {concatenated}"


def test_no_unsafe_calls_in_the_backend():
    forbidden = re.compile(r"\beval\(|\bexec\(|pickle\.loads?\(|yaml\.load\(|shell\s*=\s*True|verify\s*=\s*False|os\.system\(")
    hits = []
    for rel, source, _tree in _modules():
        for number, line in enumerate(source.splitlines(), 1):
            if forbidden.search(line) and not line.lstrip().startswith("#"):
                hits.append(f"{rel}:{number}: {line.strip()[:100]}")
    assert not hits, "Unsafe call(s):\n" + "\n".join(hits)


# ---------------------------------------------------------------------------------------- audit trail
# handler name -> audit action it must record. Removing the call, or renaming the action, fails this test.
AUDITED_HANDLERS = {
    "login": "auth.login",
    "request_dashboard_password_reset": "auth.password_reset_requested",
    "confirm_dashboard_password_reset": "auth.password_reset_completed",
    "change_dashboard_password": "account.password_changed",
    "request_dashboard_email_change": "account.email_change_requested",
    "confirm_dashboard_email_change": "account.email_changed",
    "dashboard_logout": "auth.logout",
    "login_mfa": "auth.login",
    "mfa_enroll": "auth.mfa_enroll",
    "mfa_confirm": "auth.mfa_enroll",
    "mfa_new_recovery_codes": "auth.mfa_recovery",
    "mfa_disable": "auth.mfa_disable",
    "admin_reset_mfa": "auth.mfa_reset",
    "driver_phone_login": "auth.driver_login",
    "driver_iqama_login": "auth.driver_login",
    "driver_online_logout": "auth.driver_logout",
    "admin_release_driver_device": "driver.device_release",
    "admin_reset_driver_password": "driver.password_reset",
    "driver_change_password": "account.password_changed",
    "add_user": "user.create",
    "deactivate_user": "user.deactivate",
    "edit_user": "user.update",
    "delete_user": "user.delete",
    "create_company": "company.create",
    "edit_company": "company.update",
    "delete_empty_company": "company.delete",
    "permanently_delete_company": "company.permanent_delete",
    "create_driver": "driver.create",
    "onboard_driver": "driver.onboard",
    "edit_driver": "driver.update",
    "delete_driver": "driver.delete",
    "create_vehicle": "vehicle.create",
    "edit_vehicle": "vehicle.update",
    "delete_vehicle": "vehicle.delete",
    "correct_odometer": "vehicle.odometer_correction",
    "create_driver_account": "driver_account.create",
    "link_existing_driver": "driver_account.link",
    "put_company_driver_logo": "company.driver_logo_update",
    "invite_user": "invitation.send",
    "resend_invitation": "invitation.resend",
    "accept_invitation": "invitation.accept",
    "create_live_share": "live_share.create",
    "revoke_live_share": "live_share.revoke",
    "save_fleet_settings": "settings.thresholds_update",
    "put_event_policy": "settings.event_policy_update",
    "put_phase4_settings": "geofence.settings_update",
    "add_phase4_zone": "geofence.zone_add",
    "update_phase4_zone_vehicles": "geofence.zone_vehicles_update",
    "delete_phase4_zone": "geofence.zone_delete",
    "update_branding": "branding.update",
    "monthly_fleet_export": "report.export",
    "concept_report_export": "report.export",
    "create_report": "report_subscription.create",
    "toggle_report": "report_subscription.toggle",
    "delete_report": "report_subscription.delete",
}

# Functions that are not routes but write audit rows for the routes that call them (two-step sign-in, reviewed).
AUDIT_HELPERS = {
    "verify_second_factor": "auth.mfa",  # app/mfa_db.py: every check of a code: ok, failed, locked, error
    "_check_password": "auth.mfa_password",  # features/mfa_accounts.py: a wrong password on an account-security action
    "main": "auth.mfa_reset",  # app/mfa_tools.py: the server command
}


def _audit_calls():
    """(file, enclosing handler, call node) for every audit()/audit_commit() call outside audit.py."""
    for rel, _source, tree in _modules():
        if rel == "audit.py":
            continue
        stack = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                if isinstance(node.func, ast.Name) and node.func.id in ("audit", "audit_commit"):
                    calls.append((rel, stack[-1] if stack else "<module>", node))
                self.generic_visit(node)

        calls = []
        Visitor().visit(tree)
        yield from calls


def test_sensitive_handlers_record_audit_events():
    recorded = {}
    for _rel, handler, call in _audit_calls():
        if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
            recorded.setdefault(handler, set()).add(call.args[1].value)
    problems = [f"{handler}: expected audit action '{action}', found {sorted(recorded.get(handler, []))}"
                for handler, action in {**AUDITED_HANDLERS, **AUDIT_HELPERS}.items() if action not in recorded.get(handler, set())]
    assert not problems, "Audit trail calls missing:\n" + "\n".join(problems)


def test_every_audited_handler_is_a_known_route_and_every_call_is_listed():
    route_names = {r["name"] for r in _routes()}
    assert set(AUDITED_HANDLERS) <= route_names, sorted(set(AUDITED_HANDLERS) - route_names)
    unlisted = sorted({handler for _rel, handler, _call in _audit_calls()} - set(AUDITED_HANDLERS) - set(AUDIT_HELPERS))
    assert not unlisted, f"audit() is called from handler(s) not listed in AUDITED_HANDLERS: {unlisted}"


def test_audit_action_names_are_well_formed():
    pattern = re.compile(r"^[a-z_]+\.[a-z_]+$")
    bad = []
    for rel, handler, call in _audit_calls():
        if len(call.args) < 2 or not isinstance(call.args[1], ast.Constant) or not pattern.match(str(call.args[1].value)):
            bad.append(f"{rel}:{handler}")
    assert not bad, f"audit action must be a literal like 'user.create': {bad}"


def test_audit_detail_never_names_secret_or_location_fields():
    forbidden = ("password", "token", "secret", "authorization", "latitude", "longitude", "photo", "logo_data")
    exact = {"lat", "lng", "lon"}
    bad = []
    for rel, handler, call in _audit_calls():
        for keyword in call.keywords:
            if keyword.arg == "detail" and isinstance(keyword.value, ast.Dict):
                for key in keyword.value.keys:
                    if isinstance(key, ast.Constant):
                        name = str(key.value).lower()
                        if name in exact or any(part in name for part in forbidden):
                            bad.append(f"{rel}:{handler}: detail key '{key.value}'")
    assert not bad, "\n".join(bad)


def test_failed_logins_do_not_store_the_attempted_identifier():
    by_name = {r["name"]: r["source"] for r in _routes()}
    for handler in ("login", "driver_phone_login", "driver_iqama_login"):
        source = by_name[handler]
        for call in re.findall(r"audit_commit\([^\n]*outcome='failed'[^\n]*\)", source):
            assert "email" not in call.replace("known_account", "") and "payload" not in call, (handler, call)


def test_dashboard_logout_ends_every_session_of_the_user():
    by_name = {r["name"]: r for r in _routes()}
    logout = by_name["dashboard_logout"]
    assert logout["path"] == "/api/v1/auth/logout" and logout["needs_login"]
    assert "auth_version=auth_version+1" in logout["source"].replace(" ", "")


def test_security_audit_endpoint_is_admin_only_and_company_scoped():
    route = next(r for r in _routes() if r["path"] == "/api/v1/security-audit")
    source = route["source"]
    assert route["method"] == "GET" and route["needs_login"]
    assert "allow(user, 'super_admin', 'company_admin')" in source
    assert "user.role != 'super_admin'" in source and "company_id = user.company_id" in source


def test_security_audit_module_is_registered_in_main():
    assert re.search(r"^from \.features import security_audit_log\b", (APP / "main.py").read_text(encoding="utf-8"), re.M)


def test_audit_writes_are_isolated_from_the_callers_session_state():
    source = (APP / "audit.py").read_text(encoding="utf-8")
    assert "conn.begin_nested()" in source and "db.begin_nested()" not in source, (
        "Use a connection-level savepoint: Session.begin_nested() flushes the caller's pending changes first")
    assert "except Exception" in source, "audit() must never raise into the request"
