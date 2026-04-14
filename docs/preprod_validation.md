# Pre-Production Validation Runner

Run the repo-native validation harness with one command:

```bash
BOOTSTRAP_SUPER_ADMIN_EMAIL=manash.ray@cittagent.com \
BOOTSTRAP_SUPER_ADMIN_FULL_NAME="Shivex Super-Admin" \
BOOTSTRAP_SUPER_ADMIN_PASSWORD='Shivex@2706' \
ORG_ADMIN_EMAIL=vedanth.shetty@cittagent.com \
ORG_ADMIN_PASSWORD='zaqmlp123' \
python3 scripts/preprod_validation.py --mode current-live
```

Modes:

- `current-live`: validates the current running stack with the provided live credentials and seeded validation roles.
- `quick-gate`: runs the same high-risk live checks without implying release GO status.
- `full-validation`: runs the broader regression suites after the live checks.
- `full-reset`: runs `docker compose down -v --remove-orphans` and `docker compose up -d --build` before full validation.

Optional flags:

- `--stop-on-first-defect`: stop as soon as a confirmed product defect is recorded.

Artifacts:

- JSON report: `artifacts/preprod-validation/<timestamp>/report.json`
- Markdown summary: `artifacts/preprod-validation/<timestamp>/summary.md`
- Command logs: `artifacts/preprod-validation/<timestamp>/commands/`
- Service log sweep: `artifacts/preprod-validation/<timestamp>/logs/`
- UI smoke context: `artifacts/preprod-validation/<timestamp>/smoke_context.json`

The runner reuses existing validation assets:

- `scripts/ensure_certification_orgs.py`
- `scripts/validate_isolation.py`
- `ui-web/tests/e2e/preprod-scoped-ui-smoke.spec.js`
- targeted pytest suites for financial consistency, notifications/settings, and scheduled reports

GO / NO-GO behavior:

- `current-live` and `quick-gate` are release-precheck modes and stay `NO-GO` unless a full validation run completes.
- `full-validation` can return `GO` only when all checklist items pass and nothing remains unexecuted.
