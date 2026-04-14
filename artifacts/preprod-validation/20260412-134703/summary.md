## Validation Setup
- reset steps performed: none
- exact org/plants/users/devices used or created: {"devices": [], "orgs": [], "plants": [], "users": []}
- environment used: {"analytics_url": "http://localhost:8003", "auth_url": "http://localhost:8090", "cert_python": "/Users/vedanthshetty/.pyenv/versions/3.11.9/bin/python3.11", "data_url": "http://localhost:8081", "device_url": "http://localhost:8000", "repo_root": "/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main", "reporting_url": "http://localhost:8085", "rule_url": "http://localhost:8002", "started_at": "2026-04-12T13:47:04.353979+00:00"}
- credentials source used: environment variables / provided live credentials

## Findings
- Multi-org isolation: severity=critical; affected=tenant-scope/platform; classification=confirmed product defect; production-blocking=True; root cause=Isolation validator failed on the current live stack.
- Machines page: severity=medium; affected=ui-web/platform; classification=confirmed product defect; production-blocking=False; root cause=Preprod scoped UI smoke failed on the live stack.
- Machine detail page: severity=medium; affected=ui-web/platform; classification=confirmed product defect; production-blocking=False; root cause=Preprod scoped UI smoke failed on the live stack.
- Final GO / NO-GO: severity=critical; affected=release-gate/platform; classification=confirmed product defect; production-blocking=True; root cause=8 checklist item(s) failed.

## Fixes Applied
- none

## Validation Results
- Fresh reset sanity: FAIL | Required service health verification failed.
- Multi-org isolation: FAIL | Isolation validator failed on the current live stack.
- Org / plant setup: NOT_EXECUTED | Not executed by this run.
- Device onboarding: NOT_EXECUTED | Not executed by this run.
- Real telemetry ingestion: NOT_EXECUTED | Not executed by this run.
- Telemetry / Influx contract: NOT_EXECUTED | Not executed by this run.
- Role scoping: NOT_EXECUTED | Not executed by this run.
- Machines page: FAIL | Preprod scoped UI smoke failed on the live stack.
- Machine detail page: FAIL | Preprod scoped UI smoke failed on the live stack.
- Rules: NOT_EXECUTED | Not executed by this run.
- Real rule trigger execution: NOT_EXECUTED | Not executed by this run.
- Per-rule notification recipients: FAIL | Notification and settings regression tests failed with exit code 1.
- Notification delivery intent: NOT_EXECUTED | Not executed by this run.
- Settings: FAIL | Notification and settings regression tests failed with exit code 1.
- Legacy notification migration behavior: FAIL | Notification and settings regression tests failed with exit code 1.
- Reports: NOT_EXECUTED | Not executed by this run.
- Scheduled reports: PASS | Scheduled report reliability tests passed on the current stack.
- Analytics: NOT_EXECUTED | Not executed by this run.
- Financial consistency: FAIL | Targeted financial consistency tests failed with exit code 2.
- Error handling: NOT_EXECUTED | Not executed by this run.
- Hardware lifecycle: NOT_EXECUTED | Not executed by this run.
- Hardware integrity: NOT_EXECUTED | Not executed by this run.
- Logs / runtime stability: PASS | Final log sweep found no critical runtime stability indicators in required services.
- Final GO / NO-GO: FAIL | 8 checklist item(s) failed.

## Logs Review
- all: ok | No crash-loop, unhandled exception, or duplicate scheduler tokens found in the final log sweep.

## Production Recommendation
- NO-GO: 8 checklist item(s) failed.

## Follow-ups
- Analytics needs a full-validation run before deployment.
- Fresh reset sanity: Required service health verification failed.
- Multi-org isolation: Isolation validator failed on the current live stack.
- Org / plant setup: not executed in current-live mode.
- Device onboarding: not executed in current-live mode.
- Real telemetry ingestion: not executed in current-live mode.
- Telemetry / Influx contract: not executed in current-live mode.
- Role scoping: not executed in current-live mode.
- Machines page: Preprod scoped UI smoke failed on the live stack.
- Machine detail page: Preprod scoped UI smoke failed on the live stack.
- Rules: not executed in current-live mode.
- Real rule trigger execution: not executed in current-live mode.
- Per-rule notification recipients: Notification and settings regression tests failed with exit code 1.
- Notification delivery intent: not executed in current-live mode.
- Settings: Notification and settings regression tests failed with exit code 1.
- Legacy notification migration behavior: Notification and settings regression tests failed with exit code 1.
- Reports: not executed in current-live mode.
- Analytics: not executed in current-live mode.
- Financial consistency: Targeted financial consistency tests failed with exit code 2.
- Error handling: not executed in current-live mode.
- Hardware lifecycle: not executed in current-live mode.
- Hardware integrity: not executed in current-live mode.
- Final GO / NO-GO: 8 checklist item(s) failed.
