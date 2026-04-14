## Validation Setup
- reset steps performed: none
- exact org/plants/users/devices created: {"devices": [], "orgs": [], "plants": [], "users": []}
- environment used: {"analytics_url": "http://localhost:8003", "auth_url": "http://localhost:8090", "cert_python": "/Users/vedanthshetty/.pyenv/versions/3.11.9/bin/python3.11", "data_url": "http://localhost:8081", "device_url": "http://localhost:8000", "repo_root": "/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main", "reporting_url": "http://localhost:8085", "rule_url": "http://localhost:8002", "started_at": "2026-04-08T15:07:13.911018+00:00"}

## Findings
- severity=critical; module=seeding; role=system; classification=confirmed product defect; production-blocking=True; root cause=Certification org seeding failed.
- severity=critical; module=seeding; role=system; classification=confirmed product defect; production-blocking=True; root cause=Certification org seeding failed.
- severity=critical; module=seeding; role=system; classification=confirmed product defect; production-blocking=True; root cause=Certification org seeding failed.

## Fixes Applied
- none; the runner reports defects but does not mutate product code during execution

## Validation Results
- Fresh reset sanity: FAIL | Certification org seeding failed.
- Multi-org isolation: FAIL | Certification org seeding failed.
- Org / plant setup: FAIL | Certification org seeding failed.
- Device onboarding: NOT_EXECUTED | Not executed by this run.
- Real telemetry ingestion: NOT_EXECUTED | Not executed by this run.
- Telemetry / Influx contract: NOT_EXECUTED | Not executed by this run.
- Role scoping: NOT_EXECUTED | Not executed by this run.
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
- Final GO / NO-GO: FAIL | 3 checklist item(s) failed.

## Logs Review

## Production Recommendation
- NO-GO: 3 checklist item(s) failed.

## Follow-ups
- Certification org seeding failed.
- Certification org seeding failed.
- Certification org seeding failed.
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
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
- Not executed by this run.
