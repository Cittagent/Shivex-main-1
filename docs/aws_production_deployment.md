# AWS Production Deployment Guardrails

`docker-compose.yml` is a local development stack only. It publishes host ports and uses local containers for MySQL, Redis, InfluxDB, MinIO, EMQX, Prometheus, Grafana, Mailpit, and service processes. Do not deploy it as the production architecture.

## Required Managed Or Private Services

- MySQL: Amazon RDS or Aurora MySQL in private subnets, encrypted storage, automated backups, point-in-time recovery, migration runner access through private networking only.
- Redis: ElastiCache Redis in private subnets with TLS/auth enabled and bounded stream retention.
- Object storage: private S3 buckets for datasets, reports, waste reports, exports, and snapshots. Block public access at the account and bucket level.
- Telemetry time series: managed InfluxDB or a private self-managed deployment with explicit bucket retention and backups.
- MQTT: AWS IoT Core or private EMQX. Anonymous access must be disabled in production.
- Secrets: AWS Secrets Manager or SSM Parameter Store for database credentials, JWT secrets, SMTP/API keys, MQTT credentials, and object storage credentials.

## Network Exposure

- Put databases, Redis, MQTT brokers, and internal services on private subnets/security groups.
- Expose only the public load balancer or API gateway routes intended for users and devices.
- Keep MinIO/S3 buckets private. Do not apply public bucket policies for generated artifacts.
- Restrict admin consoles such as Grafana, EMQX dashboard, and database access to VPN/bastion or SSO-protected private access.

## Configuration Rules

- Start from `.env.production.example`, not `.env`.
- Set `ENVIRONMENT=production`.
- Set `EMQX_ALLOW_ANONYMOUS=false` unless using AWS IoT Core with certificate-based device auth.
- Use strong generated credentials from Secrets Manager. Local values such as `energy`, `admin123`, `minio123`, and `energy-token` are forbidden.
- Use TLS endpoints for public and cross-AZ service traffic.

## Health, Retention, And Backups

- Health checks must fail closed when MySQL, InfluxDB, S3/object storage, Redis, or required downstream services are unavailable.
- Define lifecycle policies for S3 buckets containing datasets, exports, reports, waste reports, and snapshots.
- Keep InfluxDB bucket retention explicit.
- Keep outbox, DLQ, reconciliation, analytics artifact, report, waste, export, and Redis stream retention jobs enabled and monitored.
- Enable RDS automated backups and test restore procedures before production launch.

## Deployment Gate

A production deployment is not certified until an environment-specific infrastructure plan proves private networking, managed-service retention, backups, secret sourcing, MQTT authentication, health checks, and artifact lifecycle policies. Passing the local Docker certification does not certify AWS deployment architecture.
