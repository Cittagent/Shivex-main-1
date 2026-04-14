## Validation Setup
- reset steps performed: none
- exact org/plants/users/devices used or created: {"devices": [{"device_id": "AD00000001", "device_name": "Certification Duplicate Machine", "metadata_key": "test-01:duplicate:a", "plant_id": "7e5c8610-88fd-498d-ae6c-12592c34081b", "plant_name": "Test-01 Certification Plant A"}, {"device_id": "AD00000002", "device_name": "Certification Duplicate Machine", "metadata_key": "test-01:duplicate:b", "plant_id": "a4df4cf6-f671-4aec-845a-157538bc7891", "plant_name": "Test-01 Certification Plant B"}, {"device_id": "AD00000003", "device_name": "Smoke Device A", "metadata_key": "test-01:smoke:a", "plant_id": "7e5c8610-88fd-498d-ae6c-12592c34081b", "plant_name": "Test-01 Certification Plant A"}, {"device_id": "AD00000004", "device_name": "Smoke Device B", "metadata_key": "test-01:smoke:b", "plant_id": "a4df4cf6-f671-4aec-845a-157538bc7891", "plant_name": "Test-01 Certification Plant B"}, {"device_id": "AD00000005", "device_name": "Smoke Device C", "metadata_key": "test-01:smoke:c", "plant_id": "d313757f-5ecc-4749-8a37-ece8fb8bb7ba", "plant_name": "Test-01 Certification Plant C"}, {"device_id": "AD00000006", "device_name": "Certification Duplicate Machine", "metadata_key": "certification-validation-secondary:duplicate:a", "plant_id": "5fa28c1e-4fff-4de7-bd3d-8121833c903b", "plant_name": "Certification Validation Secondary Certification Plant A"}, {"device_id": "AD00000007", "device_name": "Certification Duplicate Machine", "metadata_key": "certification-validation-secondary:duplicate:b", "plant_id": "bfb00ae2-01b0-4287-89f4-18ed6e48dc32", "plant_name": "Certification Validation Secondary Certification Plant B"}], "orgs": [{"devices": [{"device_id": "AD00000001", "device_name": "Certification Duplicate Machine", "metadata_key": "test-01:duplicate:a", "plant_id": "7e5c8610-88fd-498d-ae6c-12592c34081b", "plant_name": "Test-01 Certification Plant A"}, {"device_id": "AD00000002", "device_name": "Certification Duplicate Machine", "metadata_key": "test-01:duplicate:b", "plant_id": "a4df4cf6-f671-4aec-845a-157538bc7891", "plant_name": "Test-01 Certification Plant B"}], "id": "SH00000001", "name": "Test-01", "operator": {"email": "certify+test-01-operator@factoryops.local", "password": "Validate123!", "role": "operator"}, "org_admin": {"email": "certify+test-01-admin@factoryops.local", "password": "Validate123!", "role": "org_admin"}, "plant_manager": {"email": "certify+test-01-pm@factoryops.local", "password": "Validate123!", "role": "plant_manager"}, "plants": [{"id": "7e5c8610-88fd-498d-ae6c-12592c34081b", "name": "Test-01 Certification Plant A"}, {"id": "a4df4cf6-f671-4aec-845a-157538bc7891", "name": "Test-01 Certification Plant B"}, {"id": "d313757f-5ecc-4749-8a37-ece8fb8bb7ba", "name": "Test-01 Certification Plant C"}], "slug": "test-01", "smoke_devices": [{"device_id": "AD00000003", "device_name": "Smoke Device A", "metadata_key": "test-01:smoke:a", "plant_id": "7e5c8610-88fd-498d-ae6c-12592c34081b", "plant_name": "Test-01 Certification Plant A"}, {"device_id": "AD00000004", "device_name": "Smoke Device B", "metadata_key": "test-01:smoke:b", "plant_id": "a4df4cf6-f671-4aec-845a-157538bc7891", "plant_name": "Test-01 Certification Plant B"}, {"device_id": "AD00000005", "device_name": "Smoke Device C", "metadata_key": "test-01:smoke:c", "plant_id": "d313757f-5ecc-4749-8a37-ece8fb8bb7ba", "plant_name": "Test-01 Certification Plant C"}], "viewer": {"email": "certify+test-01-viewer@factoryops.local", "password": "Validate123!", "role": "viewer"}}, {"devices": [{"device_id": "AD00000006", "device_name": "Certification Duplicate Machine", "metadata_key": "certification-validation-secondary:duplicate:a", "plant_id": "5fa28c1e-4fff-4de7-bd3d-8121833c903b", "plant_name": "Certification Validation Secondary Certification Plant A"}, {"device_id": "AD00000007", "device_name": "Certification Duplicate Machine", "metadata_key": "certification-validation-secondary:duplicate:b", "plant_id": "bfb00ae2-01b0-4287-89f4-18ed6e48dc32", "plant_name": "Certification Validation Secondary Certification Plant B"}], "id": "SH00000002", "name": "Certification Validation Secondary", "operator": null, "org_admin": {"email": "certify+certification-validation-secondary-admin@factoryops.local", "password": "Validate123!", "role": "org_admin"}, "plant_manager": {"email": "certify+certification-validation-secondary-pm@factoryops.local", "password": "Validate123!", "role": "plant_manager"}, "plants": [{"id": "5fa28c1e-4fff-4de7-bd3d-8121833c903b", "name": "Certification Validation Secondary Certification Plant A"}, {"id": "bfb00ae2-01b0-4287-89f4-18ed6e48dc32", "name": "Certification Validation Secondary Certification Plant B"}], "slug": "certification-validation-secondary", "smoke_devices": [], "viewer": null}], "plants": [{"id": "7e5c8610-88fd-498d-ae6c-12592c34081b", "name": "Test-01 Certification Plant A"}, {"id": "a4df4cf6-f671-4aec-845a-157538bc7891", "name": "Test-01 Certification Plant B"}, {"id": "d313757f-5ecc-4749-8a37-ece8fb8bb7ba", "name": "Test-01 Certification Plant C"}, {"id": "5fa28c1e-4fff-4de7-bd3d-8121833c903b", "name": "Certification Validation Secondary Certification Plant A"}, {"id": "bfb00ae2-01b0-4287-89f4-18ed6e48dc32", "name": "Certification Validation Secondary Certification Plant B"}], "users": [{"email": "certify+test-01-admin@factoryops.local", "password": "Validate123!", "role": "org_admin"}, {"email": "certify+test-01-pm@factoryops.local", "password": "Validate123!", "role": "plant_manager"}, {"email": "certify+certification-validation-secondary-admin@factoryops.local", "password": "Validate123!", "role": "org_admin"}, {"email": "certify+certification-validation-secondary-pm@factoryops.local", "password": "Validate123!", "role": "plant_manager"}, {"email": "certify+test-01-operator@factoryops.local", "password": "Validate123!", "role": "operator"}, {"email": "certify+test-01-viewer@factoryops.local", "password": "Validate123!", "role": "viewer"}, {"email": "manash.ray@cittagent.com", "password": "Shivex@2706", "role": "super_admin"}]}
- environment used: {"analytics_url": "http://localhost:8003", "auth_url": "http://localhost:8090", "cert_python": "/Users/vedanthshetty/.pyenv/versions/3.11.9/bin/python3.11", "data_url": "http://localhost:8081", "device_url": "http://localhost:8000", "repo_root": "/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main", "reporting_url": "http://localhost:8085", "rule_url": "http://localhost:8002", "started_at": "2026-04-11T17:57:07.260491+00:00"}
- credentials source used: environment variables / provided live credentials

## Findings
- Role scoping: severity=critical; affected=device-service/platform; classification=confirmed product defect; production-blocking=True; root cause=Role-scoped fleet visibility leaked outside the assigned plant scope.
- Logs / runtime stability: severity=critical; affected=runtime/platform; classification=confirmed product defect; production-blocking=True; root cause=Log sweep found runtime instability indicators in service logs.
- Final GO / NO-GO: severity=critical; affected=release-gate/platform; classification=confirmed product defect; production-blocking=True; root cause=8 checklist item(s) failed.

## Fixes Applied
- none

## Validation Results
- Fresh reset sanity: PASS | Required services and bootstrap logins are healthy.
- Multi-org isolation: PASS | Org isolation validator passed against the current live stack.
- Org / plant setup: PASS | Certification org bundles were seeded successfully.
- Device onboarding: PASS | Validation roles, plants, and smoke devices were provisioned.
- Real telemetry ingestion: PASS | Fresh telemetry arrived through the live MQTT ingestion path and latest/range/batch reads succeeded.
- Telemetry / Influx contract: PASS | Influx telemetry rows use the expected measurement/tag contract and downstream APIs stayed metadata-lean.
- Role scoping: FAIL | Role-scoped fleet visibility leaked outside the assigned plant scope.
- Machines page: FAIL | Preprod scoped UI smoke failed on the live stack.
- Machine detail page: FAIL | Preprod scoped UI smoke failed on the live stack.
- Rules: PASS | Scoped rule visibility for the primary org remained tenant-safe.
- Real rule trigger execution: PASS | Telemetry triggered the rule and created a live alert artifact.
- Per-rule notification recipients: FAIL | Notification and settings regression tests failed with exit code 1.
- Notification delivery intent: PASS | A single live trigger produced a single alert artifact with the intended recipient scope.
- Settings: FAIL | Notification and settings regression tests failed with exit code 1.
- Legacy notification migration behavior: FAIL | Notification and settings regression tests failed with exit code 1.
- Reports: PASS | Live energy report generation, status polling, and PDF download succeeded.
- Scheduled reports: PASS | Scheduled report reliability tests passed on the current stack.
- Analytics: NOT_EXECUTED | Not executed by this run.
- Financial consistency: FAIL | Targeted financial consistency tests failed with exit code 2.
- Error handling: NOT_EXECUTED | Not executed by this run.
- Hardware lifecycle: NOT_EXECUTED | Not executed by this run.
- Hardware integrity: NOT_EXECUTED | Not executed by this run.
- Logs / runtime stability: FAIL | Log sweep found runtime instability indicators in service logs.
- Final GO / NO-GO: FAIL | 8 checklist item(s) failed.

## Logs Review
- rule-engine-service: warning | Unexpected log token(s): traceback

## Production Recommendation
- NO-GO: 8 checklist item(s) failed.

## Follow-ups
- Analytics needs a full-validation run before deployment.
- Role scoping: Role-scoped fleet visibility leaked outside the assigned plant scope.
- Machines page: Preprod scoped UI smoke failed on the live stack.
- Machine detail page: Preprod scoped UI smoke failed on the live stack.
- Per-rule notification recipients: Notification and settings regression tests failed with exit code 1.
- Settings: Notification and settings regression tests failed with exit code 1.
- Legacy notification migration behavior: Notification and settings regression tests failed with exit code 1.
- Analytics: not executed in current-live mode.
- Financial consistency: Targeted financial consistency tests failed with exit code 2.
- Error handling: not executed in current-live mode.
- Hardware lifecycle: not executed in current-live mode.
- Hardware integrity: not executed in current-live mode.
- Logs / runtime stability: Log sweep found runtime instability indicators in service logs.
- Final GO / NO-GO: 8 checklist item(s) failed.
