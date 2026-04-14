# FactoryOPS Long-Term Requirement: Negative Telemetry Handling and Canonical Energy Accuracy

## Project Context
FactoryOPS is a multi-tenant industrial SaaS platform for machine monitoring, telemetry ingestion, machine state tracking, rules and alerts, reporting, analytics, waste analysis, and energy/loss accounting.

The current platform includes:

- `data-service` for telemetry ingestion and InfluxDB persistence
- `device-service` for machine state, live dashboard, shifts, thresholds, waste/loss, and fleet views
- `energy-service` for canonical energy aggregation and accounting
- `reporting-service` for PDF reports, demand/load factor analysis, and report history/schedules
- `analytics-service` for analytics jobs and scoped results
- `rule-engine-service` for rule evaluation, alerts, and activity generation
- `ui-web` for operator, viewer, plant manager, org admin, and super admin workflows

This requirement is specifically for long-term, production-grade handling of real sensor telemetry where some devices may send:

- negative `power`
- negative `active_power`
- negative `power_factor`
- signed values caused by clamp polarity, CT orientation, wiring direction, or bidirectional energy flow

The goal is a permanent platform-wide design, not a local patch.

## Current Real-World Problem
In live telemetry from a real sensor, the platform is receiving values such as:

- `power = -6669.82`
- `power_factor = -0.83`

This can happen in real-world deployments when:

- CT clamps are reversed
- sensor polarity is inverted
- meter direction is configured differently from the platform assumption
- power flow is genuinely bidirectional

Today, the codebase does not handle these values consistently across services.

Observed behavior from code tracing:

- some services clamp negative power to zero
- some services use raw signed power directly
- some services ignore non-positive power factor
- some services use signed power factor in calculations and insights

This inconsistency can create mismatches across:

- total energy consumption
- reports
- load factor
- peak demand
- waste analysis
- idle/off-hours/overconsumption loss accounting
- runtime and state classification
- analytics over time
- power factor insights
- reactive analysis

## Business Goal
The platform must support real industrial deployments over the long term and produce accurate, explainable, auditable outputs even when telemetry contains signed electrical values.

The result must be:

- correct for energy consumption use cases
- consistent across services
- explainable to customers
- traceable from raw telemetry to final report/output
- safe for long-term production use

## Non-Negotiable Requirement
Negative telemetry handling must be solved as a platform-level canonical data problem.

It must NOT be solved by:

- UI-only fixes
- report-only patches
- one-off clamps in isolated modules
- hiding or suppressing raw values without a formal model

## Required Long-Term Outcome
The system must distinguish between:

1. Raw electrical telemetry
2. Canonical operational telemetry used for business calculations

Raw values must remain available for diagnostics and audit.

Canonical values must be used for:

- total energy consumption
- load factor
- demand calculations
- idle/off-hours/overconsumption accounting
- waste analysis
- reports
- analytics
- long-range trend calculations

## Real-World Handling Model Required
The platform must support a formal polarity and direction model.

At minimum, there must be a configuration concept such as:

- `polarity_mode = normal`
- `polarity_mode = inverted`
- `polarity_mode = bidirectional`

This must be configurable at the correct level, for example:

- per device
- per installed hardware unit
- per CT/meter installation

The platform must not assume that all negative power means the same thing.

It must distinguish between:

### Case A: Sensor polarity / CT orientation issue
Meaning:

- the load is consuming power
- but telemetry sign is reversed because of installation orientation

Expected platform behavior:

- canonical consumption must still be positive and accurate
- reports and analytics must not show false negative consumption

### Case B: True bidirectional flow / export
Meaning:

- the device or site may actually export energy

Expected platform behavior:

- raw signed values must be preserved
- canonical import and export metrics must be separated
- consumption reports must not mix import and export incorrectly

## Required Canonical Telemetry Model
The long-term design should support a canonical model like:

- `active_power_net_w` or `active_power_net_kw`
- `active_power_import_w`
- `active_power_export_w`
- `power_factor_signed`
- `power_factor_abs` or equivalent normalized operational PF

Business calculations must use the correct canonical field, not whichever raw field happened to arrive.

## Required Accuracy Principles
For all business outputs, the system must have one authoritative interpretation path.

That means:

- energy totals must not differ by service because of sign handling
- demand and load factor must be derived from the same canonical basis
- waste/loss accounting must use the same canonical power/energy interpretation
- reports and dashboards must agree for the same device/window
- analytics must not diverge from reports for the same data window

## Required Coverage
The permanent solution must cover all of the following:

### 1. Telemetry ingestion
- MQTT/raw ingest path
- normalization rules
- preservation of raw values
- generation of canonical values

### 2. Storage
- what gets stored in Influx as raw
- what gets stored in Influx as canonical
- what gets stored in projection/state tables
- what metadata/config drives normalization

### 3. Total energy consumption
- must remain accurate for real-world signed telemetry
- must be explainable from raw data to final kWh
- must remain non-negative for standard consumption reports when polarity is inverted

### 4. Demand and peak demand
- must use canonical consumption power
- must not be distorted by negative raw power due to polarity reversal

### 5. Load factor
- must be calculated from the same canonical energy/power basis as reports
- must remain meaningful under real sensor polarity issues

### 6. Waste analysis and loss accounting
- idle loss
- off-hours loss
- overconsumption
- total loss
- all must use consistent normalized values

### 7. Machine runtime and state
- running/stopped
- in-load/idle/unloaded/unknown
- state logic must not be falsely broken by signed power reversal

### 8. Reports
- energy consumption report
- load factor / demand calculations
- power factor insights
- reactive analysis
- daily breakdown
- per-device quality/method indicators
- PDF output must be consistent with canonical calculation

### 9. Analytics
- analytics jobs
- trend lines
- aggregates over time
- plant/org scoped analysis

### 10. Auditability
For any number shown to a client, the platform must be able to explain:

- raw telemetry used
- normalization applied
- canonical values used
- calculation method used
- final reported value

## Required Traceability / Proof Model
The solution must allow a client-facing proof path for every important number.

For a selected report/device/window, the system should be able to show:

- report window
- first relevant telemetry timestamp
- last relevant telemetry timestamp
- number of samples used
- whether raw power was signed
- whether normalization was applied
- whether polarity correction was used
- total runtime minutes or effective calculation duration
- average canonical power
- peak canonical power
- final total energy
- final total cost
- calculation method used
- quality or confidence band

## Required Output Semantics
The platform must stop mixing raw signed values and business values without clarity.

It must have clear semantics for:

- diagnostic telemetry
- operational telemetry
- financial/consumption telemetry

The UI and reports must make this distinction clear where needed.

## Required Guardrails
The long-term implementation must prevent:

- negative consumption totals in standard consumption reports due only to polarity reversal
- false PF penalty conclusions from signed PF values caused by sensor orientation
- mismatch between dashboard energy and report energy for the same window
- mismatch between analytics and canonical report totals
- service-by-service divergence in sign interpretation

## Current Codebase Risk Summary
From current tracing, the following risk exists:

- `energy-service` and parts of `device-service` clamp negative power and are safer
- `reporting-service` can still use raw signed power and signed PF directly
- `reactive` and PF analysis are especially vulnerable to misleading results
- `idle_running` derived-power fallback also needs normalization consistency
- ingestion currently stores raw telemetry without a platform-wide canonical normalization layer

## Required Deliverable for Future Implementation
The GenAI model or implementation owner must produce:

1. Root-cause architecture analysis
2. Canonical telemetry semantics design
3. Polarity configuration model
4. Ingestion/storage normalization design
5. Cross-service impact plan
6. Backward compatibility and migration strategy
7. Test strategy
8. Validation strategy for real hardware scenarios

## Required Engineering Constraints
The long-term implementation must be:

- permanent
- production-grade
- minimal but complete
- consistent across services
- backward-compatible where necessary
- auditable
- explainable to customers

It must not be:

- a UI workaround
- a reporting-only patch
- a hardcoded clamp without configuration semantics
- a one-service-only fix

## Explicit Ask for the GenAI Model
Design and propose a permanent implementation plan for negative telemetry and polarity handling in this FactoryOPS codebase so that:

- total energy consumption is always accurate
- reports are trustworthy
- load factor and demand remain correct
- waste/loss analysis remains correct
- runtime and machine state remain stable
- analytics over time remain consistent
- raw telemetry remains auditable
- canonical values are used consistently everywhere

The plan must be grounded in this current architecture and must identify exactly what needs to change in:

- `data-service`
- `device-service`
- `energy-service`
- `reporting-service`
- shared telemetry/accounting utilities
- relevant schema/configuration layers

## Priority
High.

This is a long-term correctness and trust requirement for real industrial deployments.
