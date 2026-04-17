# Reporting Validation Freshness Protocol

## Why this exists
Validation must never treat legacy PDFs/report rows as evidence for current deploy quality.

## Hard rule
Only report rows and PDFs generated **after the active cutoff timestamp** are valid evidence.
Anything pre-cutoff is explicitly invalid for rollout decisions.

## Required procedure
1. Run tenant-scoped reset before validation:
   - `scripts/validation/reset_reporting_validation_scope.sh --tenant <TENANT_ID> --yes`
2. Read cutoff marker written by reset:
   - `artifacts/validation-cutoffs/<TENANT_ID>.cutoff`
3. Generate fresh reports after reset.
4. Assert freshness gate before accepting evidence:
   - `scripts/validation/assert_reporting_freshness.sh --tenant <TENANT_ID>`
5. Use only post-cutoff report IDs/PDFs in validation sign-off.

## Explicitly forbidden evidence
- Downloaded PDFs from before cutoff.
- `energy_reports` rows created before cutoff.
- Any legacy artifact not tied to post-cutoff report IDs.

## Scope of reset
The reset script intentionally clears tenant-scoped reporting evidence:
- MinIO prefix: `reports/<TENANT_ID>/`
- MySQL tables: `energy_reports`, `scheduled_reports` (for that tenant)

This guarantees an unambiguous post-reset validation path.
