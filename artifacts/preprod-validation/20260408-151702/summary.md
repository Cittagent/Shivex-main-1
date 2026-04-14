## Validation Setup
- reset steps performed: none
- exact org/plants/users/devices created: {"devices": [{"device_id": "AD00000001", "device_name": "Certification Duplicate Machine", "metadata_key": "test-01:duplicate:a", "plant_id": "a3070e68-1d36-4380-b3dd-70f600febff5", "plant_name": "Test-01 Certification Plant A"}, {"device_id": "AD00000002", "device_name": "Certification Duplicate Machine", "metadata_key": "test-01:duplicate:b", "plant_id": "80cfadd9-0d86-4c0c-bf00-6fff269e4908", "plant_name": "Test-01 Certification Plant B"}, {"device_id": "AD00000003", "device_name": "Certification Duplicate Machine", "metadata_key": "certification-validation-secondary:duplicate:a", "plant_id": "e46d8a93-31ea-46ca-9a3b-060f2566b0f9", "plant_name": "Certification Validation Secondary Certification Plant A"}, {"device_id": "AD00000004", "device_name": "Certification Duplicate Machine", "metadata_key": "certification-validation-secondary:duplicate:b", "plant_id": "9f70b363-a15b-4b05-948c-89531d501d11", "plant_name": "Certification Validation Secondary Certification Plant B"}, {"device_id": "AD00000023", "device_name": "Smoke Device A", "plant_id": "a3070e68-1d36-4380-b3dd-70f600febff5", "plant_name": "Test-01 Certification Plant A"}, {"device_id": "AD00000024", "device_name": "Smoke Device B", "plant_id": "80cfadd9-0d86-4c0c-bf00-6fff269e4908", "plant_name": "Test-01 Certification Plant B"}, {"device_id": "AD00000025", "device_name": "Smoke Device C", "plant_id": "2af2992b-184d-4be5-8990-4b6645ee5f36", "plant_name": "Test-01 Certification Plant C"}], "orgs": [{"devices": [{"device_id": "AD00000001", "device_name": "Certification Duplicate Machine", "metadata_key": "test-01:duplicate:a", "plant_id": "a3070e68-1d36-4380-b3dd-70f600febff5", "plant_name": "Test-01 Certification Plant A"}, {"device_id": "AD00000002", "device_name": "Certification Duplicate Machine", "metadata_key": "test-01:duplicate:b", "plant_id": "80cfadd9-0d86-4c0c-bf00-6fff269e4908", "plant_name": "Test-01 Certification Plant B"}], "id": "3052b75a-54da-4d8f-9738-4690991c3a61", "name": "Test-01", "operator": {"email": "certify+test-01-operator@factoryops.local", "password": "Validate123!", "role": "operator"}, "org_admin": {"email": "certify+test-01-admin@factoryops.local", "password": "Validate123!", "role": "org_admin"}, "plant_manager": {"email": "certify+test-01-pm@factoryops.local", "password": "Validate123!", "role": "plant_manager"}, "plants": [{"id": "a3070e68-1d36-4380-b3dd-70f600febff5", "name": "Test-01 Certification Plant A"}, {"id": "80cfadd9-0d86-4c0c-bf00-6fff269e4908", "name": "Test-01 Certification Plant B"}, {"id": "2af2992b-184d-4be5-8990-4b6645ee5f36", "name": "Test-01 Certification Plant C"}], "slug": "test-01", "smoke_devices": [{"device_id": "AD00000023", "device_name": "Smoke Device A", "plant_id": "a3070e68-1d36-4380-b3dd-70f600febff5", "plant_name": "Test-01 Certification Plant A"}, {"device_id": "AD00000024", "device_name": "Smoke Device B", "plant_id": "80cfadd9-0d86-4c0c-bf00-6fff269e4908", "plant_name": "Test-01 Certification Plant B"}, {"device_id": "AD00000025", "device_name": "Smoke Device C", "plant_id": "2af2992b-184d-4be5-8990-4b6645ee5f36", "plant_name": "Test-01 Certification Plant C"}], "viewer": {"email": "certify+test-01-viewer@factoryops.local", "password": "Validate123!", "role": "viewer"}}, {"devices": [{"device_id": "AD00000003", "device_name": "Certification Duplicate Machine", "metadata_key": "certification-validation-secondary:duplicate:a", "plant_id": "e46d8a93-31ea-46ca-9a3b-060f2566b0f9", "plant_name": "Certification Validation Secondary Certification Plant A"}, {"device_id": "AD00000004", "device_name": "Certification Duplicate Machine", "metadata_key": "certification-validation-secondary:duplicate:b", "plant_id": "9f70b363-a15b-4b05-948c-89531d501d11", "plant_name": "Certification Validation Secondary Certification Plant B"}], "id": "72da8caa-56b8-42ed-addb-349ad0821eb2", "name": "Certification Validation Secondary", "org_admin": {"email": "certify+certification-validation-secondary-admin@factoryops.local", "pa
- environment used: {"analytics_url": "http://localhost:8003", "auth_url": "http://localhost:8090", "cert_python": "/Users/vedanthshetty/.pyenv/versions/3.11.9/bin/python3.11", "data_url": "http://localhost:8081", "device_url": "http://localhost:8000", "repo_root": "/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main", "reporting_url": "http://localhost:8085", "rule_url": "http://localhost:8002", "started_at": "2026-04-08T15:17:02.390731+00:00"}

## Findings
- confirmed issues only: none

## Fixes Applied
- none; the runner reports defects but does not mutate product code during execution

## Validation Results
- Fresh reset sanity: PASS | Bootstrap and validation logins succeeded for the full role matrix.
- Multi-org isolation: PASS | Certification org bundles were seeded successfully.
- Org / plant setup: PASS | Validation roles, plants, and smoke devices were provisioned.
- Device onboarding: PASS | Device onboarding contract rejected missing plant and maintained one device per plant.
- Real telemetry ingestion: PASS | Real MQTT telemetry was ingested and surfaced through the live telemetry API.
- Telemetry / Influx contract: PASS | Influx contained fresh points for the device and did not expose forbidden duplicated metadata fields.
- Role scoping: PASS | Bootstrap and validation logins succeeded for the full role matrix.
- Machines page: NOT_EXECUTED | Not executed by this run.
- Machine detail page: NOT_EXECUTED | Not executed by this run.
- Rules: NOT_EXECUTED | Not executed by this run.
- Real rule trigger execution: NOT_EXECUTED | Not executed by this run.
- Per-rule notification recipients: NOT_EXECUTED | Not executed by this run.
- Notification delivery intent: NOT_EXECUTED | Not executed by this run.
- Settings: NOT_EXECUTED | Not executed by this run.
- Legacy notification migration behavior: NOT_EXECUTED | Not executed by this run.
- Reports: NOT_EXECUTED | Not executed by this run.
- Scheduled reports: NOT_EXECUTED | Not executed by this run.
- Analytics: NOT_EXECUTED | Not executed by this run.
- Financial consistency: NOT_EXECUTED | Not executed by this run.
- Error handling: NOT_EXECUTED | Not executed by this run.
- Hardware lifecycle: NOT_EXECUTED | Not executed by this run.
- Hardware integrity: NOT_EXECUTED | Not executed by this run.
- Logs / runtime stability: NOT_EXECUTED | Not executed by this run.
- Final GO / NO-GO: FAIL | Quick gate does not execute the full release checklist.

## Logs Review

## Production Recommendation
- NO-GO: Quick gate does not execute the full release checklist.

## Follow-ups
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
