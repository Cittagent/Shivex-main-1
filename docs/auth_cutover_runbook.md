# FactoryOPS Auth Cutover Runbook
## Auth is always enforced in Production

### When to run this

After all of the following are true:
- Phase 9 E2E tests pass with auth enforcement enabled
- All users are created in the auth system
- Web frontend login is deployed and tested
- Mobile app with auth is distributed to all operators
- All service-to-service internal calls have `X-Internal-Service` header

### Pre-flight checklist

- [ ] `pytest tests/e2e/test_10_auth.py -v` passes
- [ ] At least one user per role exists in the system
- [ ] Web app login and logout work
- [ ] Mobile login works on all test devices
- [ ] All internal service calls are sending `X-Internal-Service`
- [ ] `JWT_SECRET_KEY` is a production secret
- [ ] A database backup has been taken

### Cutover steps

**Step 1: Verify auth enforcement for non-critical services first**

In `.env`, keep:

```bash
AUTH_ALWAYS_ON=true
```

Override individual services in `docker-compose.yml`:

```yaml
reporting-service:
  environment:
    AUTH_ALWAYS_ON: "true"

waste-analysis-service:
  environment:
    AUTH_ALWAYS_ON: "true"

analytics-service:
  environment:
    AUTH_ALWAYS_ON: "true"
```

Redeploy:

```bash
docker compose up -d reporting-service waste-analysis-service analytics-service
```

Verify:

```bash
pytest tests/e2e/test_10_auth.py::TestMiddlewarePermissive -v
```

**Step 2: Keep auth enforcement enabled for core services**

Update `docker-compose.yml`:

```yaml
device-service:
  environment:
    AUTH_ALWAYS_ON: "true"
energy-service:
  environment:
    AUTH_ALWAYS_ON: "true"
rule-engine-service:
  environment:
    AUTH_ALWAYS_ON: "true"
data-service:
  environment:
    AUTH_ALWAYS_ON: "true"
copilot-service:
  environment:
    AUTH_ALWAYS_ON: "true"
```

Redeploy:

```bash
docker compose up -d
```

**Step 3: Full validation**

```bash
pytest tests/e2e/ -v
```

All tests must pass.

**Step 4: Keep auth enforcement global**

In `.env`:

```bash
AUTH_ALWAYS_ON=true
```

Remove the temporary per-service overrides from `docker-compose.yml`, then redeploy:

```bash
docker compose up -d
```

### Rollback

If anything fails, rollback in under two minutes:

```bash
AUTH_ALWAYS_ON=true
docker compose up -d
```

No database changes. No data loss. Immediate rollback.

## Service-to-service `X-Internal-Service` header

Every backend-to-backend call must include:

```http
X-Internal-Service: <calling-service-name>
```

This bypasses end-user JWT validation through the shared middleware and records the caller identity as `internal_service`.

### 1. `data-service` -> `device-service` `POST /api/v1/devices/{id}/live-update`

File: `/Users/vedanthshetty/Desktop/Dev-Test/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/services/outbox_relay.py`

Before:

```python
response = await self._http_client.post(url, json=payload)
```

After:

```python
response = await self._http_client.post(
    url,
    json=payload,
    headers={"X-Internal-Service": "data-service"},
)
```

### 2. `data-service` -> `energy-service` `POST /api/v1/energy/live-update`

File: `/Users/vedanthshetty/Desktop/Dev-Test/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/services/outbox_relay.py`

Before:

```python
response = await self._http_client.post(url, json=payload)
```

After:

```python
response = await self._http_client.post(
    url,
    json=payload,
    headers={"X-Internal-Service": "data-service"},
)
```

### 3. `data-service` -> `rule-engine-service` `POST /api/v1/rules/evaluate`

File: `/Users/vedanthshetty/Desktop/Dev-Test/FactoryOPS-Cittagent-Obeya-main/services/data-service/src/services/rule_engine_client.py`

Before:

```python
response = await self.client.post(
    url,
    json=request_data,
)
```

After:

```python
response = await self.client.post(
    url,
    json=request_data,
    headers={"X-Internal-Service": "data-service"},
)
```

### 4. `device-service` -> `energy-service` `DELETE /api/v1/energy/device-state/{id}`

Status on March 27, 2026:

No matching delete call or matching energy-service endpoint exists in the current repository snapshot. Before rolling the auth cutover for all core services, implement the delete sync and include:

```python
headers={"X-Internal-Service": "device-service"}
```

in that outbound request.

### 5. `waste-analysis-service` -> `device-service` waste config fetch

File: `/Users/vedanthshetty/Desktop/Dev-Test/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/src/services/remote_clients.py`

Before:

```python
resp = await client.get(f"{settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}/waste-config")
```

After:

```python
resp = await client.get(
    f"{settings.DEVICE_SERVICE_URL}/api/v1/devices/{device_id}/waste-config",
    headers={"X-Internal-Service": "waste-analysis-service"},
)
```

### 6. `waste-analysis-service` -> `reporting-service` tariff fetch

File: `/Users/vedanthshetty/Desktop/Dev-Test/FactoryOPS-Cittagent-Obeya-main/services/waste-analysis-service/src/services/remote_clients.py`

Before:

```python
resp = await client.get(f"{settings.REPORTING_SERVICE_URL}/api/v1/settings/tariff")
```

After:

```python
resp = await client.get(
    f"{settings.REPORTING_SERVICE_URL}/api/v1/settings/tariff",
    headers={"X-Internal-Service": "waste-analysis-service"},
)
```

### 7. `analytics-service` -> `data-export-service`

File: `/Users/vedanthshetty/Desktop/Dev-Test/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/src/services/readiness_orchestrator.py`

Before:

```python
async with session.post(
    url,
    json=payload,
    timeout=aiohttp.ClientTimeout(total=20),
) as resp:
```

After:

```python
async with session.post(
    url,
    json=payload,
    headers={"X-Internal-Service": "analytics-service"},
    timeout=aiohttp.ClientTimeout(total=20),
) as resp:
```

### 8. `analytics-service` -> `data-service`

File: `/Users/vedanthshetty/Desktop/Dev-Test/FactoryOPS-Cittagent-Obeya-main/services/analytics-service/src/services/dataset_service.py`

Before:

```python
resp = await client.get(url, params=params)
```

After:

```python
resp = await client.get(url, params=params, headers={"X-Internal-Service": "analytics-service"})
```

### 9. `copilot-service` -> `data-service`

File: `/Users/vedanthshetty/Desktop/Dev-Test/FactoryOPS-Cittagent-Obeya-main/services/copilot-service/src/integrations/data_service_client.py`

Before:

```python
res = await client.get(url, params=params)
```

After:

```python
res = await client.get(
    url,
    params=params,
    headers={"X-Internal-Service": "copilot-service"},
)
```

### 10. `copilot-service` -> `reporting-service`

File: `/Users/vedanthshetty/Desktop/Dev-Test/FactoryOPS-Cittagent-Obeya-main/services/copilot-service/src/integrations/service_clients.py`

Before:

```python
res = await client.get(url)
```

After:

```python
res = await client.get(url, headers={"X-Internal-Service": "copilot-service"})
```
