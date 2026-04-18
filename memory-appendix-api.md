# API Appendix

- Repository memory overview: [memory.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory.md)
- DB schema appendix: [memory-appendix-db.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)
- Certainty note:
  - endpoint existence, mounted prefixes, and DTO names are `Confirmed from code` unless marked otherwise in-line
  - schema/storage implications referenced here should be cross-checked against [memory-appendix-db.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

## 1. API Surface Overview

### Services exposing HTTP APIs

| Service | Mounted app/router file(s) | Base URL / prefix | Browser-facing vs internal | Auth style |
|---|---|---|---|---|
| `auth-service` | `services/auth-service/app/main.py`, `app/api/v1/*.py` | service root `:8090`; main prefixes `/api/v1/auth`, `/api/v1/tenants`, `/api/admin` | Browser-facing and admin-facing | `Confirmed from code`: public login/refresh/forgot/reset/invite-status routes; authenticated routes use JWT access token via shared/auth deps; refresh also uses HttpOnly cookie for web |
| `device-service` | `services/device-service/app/__init__.py`, `app/api/v1/router.py` | service root `:8000`; mounted under `/api/v1`; sub-prefixes `/devices`, `/settings` | Browser-facing plus internal endpoints | `Confirmed from code`: shared auth middleware; tenant scope from JWT/headers; some write endpoints enforce role checks in handler |
| `data-service` | `services/data-service/src/main.py`, `src/api/routes.py`, `src/api/websocket.py` | service root `:8081`; REST prefix default `/api/v1/data`; websocket `/ws/*` | Browser-facing telemetry APIs and internal ingest support | `Confirmed from code`: shared auth middleware for HTTP; tenant required for most REST telemetry queries. `Needs runtime verification`: websocket auth enforcement path |
| `energy-service` | `services/energy-service/app/main.py`, `app/api/routes.py` | service root `:8010`; prefix `/api/v1/energy` | Mostly internal plus browser-facing summaries | `Confirmed from code`: shared auth middleware; feature gate on monthly calendar |
| `rule-engine-service` | `services/rule-engine-service/app/__init__.py`, `app/api/v1/router.py` | service root `:8002`; mounted under `/api/v1` | Browser-facing rule/alert APIs plus internal evaluation | `Confirmed from code`: shared auth middleware plus `require_feature("rules")` on mounted router |
| `analytics-service` | `services/analytics-service/src/main.py`, `src/api/routes/*.py` | service root `:8003`; health under `/health/*`, analytics under `/api/v1/analytics` | Browser-facing job APIs plus ops endpoints | `Confirmed from code`: shared auth middleware; tenant derived from request context |
| `reporting-service` | `services/reporting-service/src/main.py`, `src/handlers/*.py` | service root `:8085`; prefixes `/api/reports/*`, `/api/v1/settings/*` | Browser-facing report APIs plus internal tariff/settings use | `Confirmed from code`: shared auth middleware; reports gated by `require_feature("reports")`; settings gated by `require_feature("settings")` |
| `waste-analysis-service` | `services/waste-analysis-service/src/main.py`, `src/handlers/waste_analysis.py` | service root `:8087`; prefix `/api/v1/waste` | Browser-facing job APIs | `Confirmed from code`: shared auth middleware and `require_feature("waste_analysis")` |
| `copilot-service` | `services/copilot-service/src/main.py`, `src/api/chat.py` | service root `:8007`; routes `/api/v1/copilot/*` | Browser-facing | `Confirmed from code`: shared auth middleware and `require_feature("copilot")` |
| `data-export-service` | `services/data-export-service/main.py` | service root `:8080`; routes `/api/v1/exports/*` | Primarily internal/service-facing, but callable via frontend proxy | `Confirmed from code`: shared auth middleware; tenant required for export routes |

### Frontend-facing proxy prefixes

`Confirmed from code` in `ui-web/next.config.ts`:

| Frontend path | Backend target |
|---|---|
| `/backend/device/:path*` | `device-service` |
| `/backend/data/:path*` | `data-service` |
| `/backend/rule-engine/:path*` | `rule-engine-service` |
| `/backend/analytics/:path*` | `analytics-service` |
| `/backend/data-export/:path*` | `data-export-service` |
| `/backend/reporting/:path*` | `reporting-service` |
| `/backend/copilot/:path*` | `copilot-service` |
| `/backend/auth/:path*` | `auth-service` |
| `/api/reports/:path*` | `reporting-service /api/reports/:path*` |
| `/api/waste/:path*` | `waste-analysis-service /api/v1/waste/:path*` |

### Route-discovery caveats

- `Confirmed from code`: `services/data-service/src/api/telemetry.py` defines duplicate `/telemetry/{device_id}` and `/stats/{device_id}` handlers, but `src/main.py` mounts `create_router()` from `src/api/routes.py`, not `api/telemetry.py`. Treat `api/telemetry.py` as defined but not obviously mounted.
- `Confirmed from code`: `services/rule-engine-service/app/api/v1/evaluation.py` is intentionally empty and says the evaluate endpoint moved into `rules.py`.

## 2. Endpoint Catalog By Service

### Auth Service

Endpoint group refs:
- `services/auth-service/app/api/v1/auth.py`
- `services/auth-service/app/api/v1/admin.py`
- `services/auth-service/app/api/v1/orgs.py`
- schemas: `services/auth-service/app/schemas/auth.py`

#### Auth and session endpoints

| Method | Full path | Purpose | Auth | Scope / role | Params | Request body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `POST` | `/api/v1/auth/login` | Login and set refresh cookie | No | public | none | `LoginRequest { email, password }` | `TokenResponse { access_token, refresh_token=null for browser, token_type, expires_in }` | `401 INVALID_CREDENTIALS`, `403 PASSWORD_SETUP_REQUIRED`, `403 ACCOUNT_DISABLED` | `auth.py:84`; `AuthService.login` |
| `POST` | `/api/v1/auth/refresh` | Rotate refresh token and return new access token | No for cookie/body token path | public refresh | none | optional `RefreshRequest { refresh_token? }`; may also use cookie | `TokenResponse` | `401 MISSING_REFRESH_TOKEN`, token expiry/revocation errors, `403 INVALID_ORIGIN` | `auth.py:92`; `AuthService.refresh` |
| `POST` | `/api/v1/auth/logout` | Revoke access/refresh token and clear cookie | Optional bearer/cookie | current session | none | optional `LogoutRequest { refresh_token? }` | `{ message }` | none stable beyond auth errors | `auth.py:113`; `AuthService.logout` |
| `GET` | `/api/v1/auth/action-token/{token}/status` | Check invite/reset token status | No | public | `token` path | none | `ActionTokenStatusResponse { status, action_type?, email?, full_name? }` | invalid token returns `status=invalid` rather than 4xx | `auth.py:137`; `AuthService.get_action_token_status` |
| `POST` | `/api/v1/auth/invitations/accept` | Set password from invite token | No | public | none | `AcceptInvitationRequest { token, password, confirm_password }` | `GenericMessageResponse` | `422 PASSWORD_MISMATCH`, invalid/expired token | `auth.py:142`; `AuthService.accept_invitation` |
| `POST` | `/api/v1/auth/password/forgot` | Request password reset email | No | public | none | `PasswordForgotRequest { email }` | `GenericMessageResponse` | intentionally suppresses account existence | `auth.py:158`; `AuthService.request_password_reset` |
| `POST` | `/api/v1/auth/password/reset` | Reset password using action token | No | public | none | `PasswordResetRequest { token, password, confirm_password }` | `GenericMessageResponse` | invalid/expired token | `auth.py:171`; `AuthService.reset_password` |
| `GET` | `/api/v1/auth/me` | Return authenticated user, tenant, plant_ids, entitlements | Yes | any authenticated; super-admin may send `X-Target-Tenant-Id` | header `X-Target-Tenant-Id` for super-admin | none | `MeResponse { user, tenant?, plant_ids, entitlements? }` | `404 TENANT_NOT_FOUND`, `403 TENANT_SUSPENDED`, token invalidation errors | `auth.py:182`; `AuthService.get_user_by_token_claims` + org/user repos |

#### Super-admin endpoints

| Method | Full path | Purpose | Auth | Scope / role | Params | Request body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `POST` | `/api/admin/tenants` | Create tenant/org | Yes | `super_admin` only | none | `CreateTenantRequest { name, slug }` | `TenantResponse` | `409 SLUG_TAKEN`, `503 TENANT_ID_ALLOCATION_FAILED` | `admin.py:21`; `OrgRepository.create` |
| `GET` | `/api/admin/tenants` | List all tenants | Yes | `super_admin` only | none | none | `list[TenantResponse]` | none explicit | `admin.py:42`; `OrgRepository.list_all` |
| `POST` | `/api/admin/users` | Create org admin | Yes | `super_admin` only | none | `CreateUserRequest`; role must be `org_admin`, password required | `UserResponse` | `422 INVALID_ROLE`, `404 TENANT_NOT_FOUND`, `409 EMAIL_TAKEN`, `422 PASSWORD_REQUIRED` | `admin.py:48`; `UserRepository.create` |
| `GET` | `/api/admin/users` | List users globally or by tenant | Yes | `super_admin` only | `tenant_id?` | none | `list[UserResponse]` | none explicit | `admin.py:92`; direct DB query or `UserRepository.list_by_tenant` |

#### Tenant/org management endpoints

| Method | Full path | Purpose | Auth | Scope / role | Params | Request body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `POST` | `/api/v1/tenants/{tenant_id}/plants` | Create plant | Yes | `require_tenant_admin_or_above`; tenant match enforced | `tenant_id` | `CreatePlantRequest { name, location?, timezone }` | `PlantResponse` | `404 ORG_NOT_FOUND` | `orgs.py:88`; `PlantRepository.create` |
| `GET` | `/api/v1/tenants/{tenant_id}/plants` | List plants | Yes | any authenticated within tenant | `tenant_id` | none | `list[PlantResponse]` | tenant scope errors | `orgs.py:108`; `PlantRepository.list_by_tenant` |
| `POST` | `/api/v1/tenants/{tenant_id}/users` | Create tenant user | Yes | `super_admin`, `org_admin`, `plant_manager`; role restrictions enforced | `tenant_id` | `CreateUserRequest { email, full_name?, role, tenant_id, plant_ids, password? }` | `UserResponse` | `403 FORBIDDEN`, `403 ROLE_ESCALATION_FORBIDDEN`, `422 TENANT_ID_MISMATCH`, `409 EMAIL_TAKEN`, `403 INVALID_PLANT_IDS`, `404 ORG_NOT_FOUND` | `orgs.py:120`; `UserRepository.create`, `AuthService.send_invitation` |
| `GET` | `/api/v1/tenants/{tenant_id}/users` | List tenant users | Yes | tenant admin or above | `tenant_id` | none | `list[UserResponse]` | tenant scope errors | `orgs.py:246`; `UserRepository.list_by_tenant` |
| `GET` | `/api/v1/tenants/{tenant_id}/entitlements` | Get effective entitlements | Yes | tenant admin or above | `tenant_id` | none | `FeatureEntitlementsResponse` | `404 ORG_NOT_FOUND` | `orgs.py:258`; `build_feature_entitlement_state` |
| `PUT` | `/api/v1/tenants/{tenant_id}/entitlements` | Update org premium grants or role matrix | Yes | super-admin updates premium grants; org_admin updates role matrix | `tenant_id` | `UpdateEntitlementsRequest { premium_feature_grants?, role_feature_matrix? }` | `FeatureEntitlementsResponse` | `403 FEATURE_SCOPE_DENIED`, `422 ROLE_MATRIX_REQUIRED`, `422 PREMIUM_GRANTS_REQUIRED`, `404 ORG_NOT_FOUND` | `orgs.py:277`; `OrgRepository.update_entitlements` |
| `PUT` / `PATCH` | `/api/v1/tenants/{tenant_id}/users/{user_id}` | Update user | Yes | tenant admin or above | `tenant_id`, `user_id` | `UpdateUserRequest { full_name?, role?, is_active?, plant_ids? }` | `UserResponse` | `404 USER_NOT_FOUND`, `403 ROLE_ESCALATION_FORBIDDEN` | `orgs.py:351`; `UserRepository.update`, token revocation on permission change |
| `GET` | `/api/v1/tenants/{tenant_id}/users/{user_id}/plant-access` | Get user plant assignments | Yes | tenant admin or above | `tenant_id`, `user_id` | none | `{ plant_ids: string[] }` | `404 USER_NOT_FOUND` | `orgs.py:404`; `UserRepository.get_plant_ids` |
| `POST` | `/api/v1/tenants/{tenant_id}/users/{user_id}/resend-invite` | Resend invite to pending user | Yes | `super_admin`, `org_admin`, `plant_manager`; pending invite only | `tenant_id`, `user_id` | none | `GenericMessageResponse` | `409 INVITE_NOT_PENDING`, `403 FORBIDDEN`, `403 ROLE_ESCALATION_FORBIDDEN` | `orgs.py:420`; `AuthService.resend_invitation` |
| `PATCH` | `/api/v1/tenants/{tenant_id}/users/{user_id}/deactivate` | Deactivate user | Yes | tenant admin or above | `tenant_id`, `user_id` | none | `{ message }` | `404 USER_NOT_FOUND` | `orgs.py:466`; `UserRepository.update`, token revocation |

### Device Service

Endpoint group refs:
- `services/device-service/app/__init__.py`
- `services/device-service/app/api/v1/router.py`
- `services/device-service/app/api/v1/settings.py`
- `services/device-service/app/api/v1/devices.py`
- schemas: `services/device-service/app/schemas/device.py`

#### Health and ops

| Method | Full path | Purpose | Auth | Response | Handler |
|---|---|---|---|---|---|
| `GET` | `/health` | Liveness | No | health JSON | `app/__init__.py:674` |
| `GET` | `/ready` | Readiness | No | readiness JSON | `app/__init__.py:688` |
| `GET` | `/metrics` | Metrics | No | metrics JSON | `app/__init__.py:716` |

#### Settings endpoints

| Method | Full path | Purpose | Auth | Scope / role | Query | Body | Response | Handler / service |
|---|---|---|---|---|---|---|---|---|
| `GET` | `/api/v1/settings/waste-config` | Get tenant/site default waste config | Yes | feature `settings` | `tenant_id?` | none | `dict { success, ...config }` | `settings.py:26`; `IdleRunningService.get_site_waste_config` |
| `PUT` | `/api/v1/settings/waste-config` | Set tenant/site default waste config | Yes | feature `settings` | none | `SiteWasteConfigRequest { default_unoccupied_* times, timezone?, updated_by?, tenant_id? }` | `dict { success, ...config }` | `settings.py:42`; `IdleRunningService.set_site_waste_config` |

#### Device/property/dashboard/hardware/shift/health/idle endpoints

`Confirmed from code`: all below are under `/api/v1/devices`.

| Method | Full path | Purpose | Auth | Scope / role | Query / path | Body | Response schema | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `GET` | `/api/v1/devices/properties` | All-device discovered properties | Yes | tenant-scoped; plant-scoped for lower roles | `limit`, `offset` | none | raw `dict` with `devices`, `all_properties` | none explicit | `devices.py:505`; `DevicePropertyService.get_all_devices_properties` |
| `POST` | `/api/v1/devices/properties/common` | Intersect common properties across device_ids | Yes | tenant-scoped; plant access validated | body JSON with `device_ids` | ad-hoc JSON | `dict` | `403 DEVICE_ACCESS_DENIED` | `devices.py:539`; `DevicePropertyService.get_common_properties` |
| `GET` | `/api/v1/devices/dashboard/summary` | Fleet/home dashboard summary | Yes | tenant/plant-scoped | `plant_id?` | none | `DashboardSummaryResponse` | none explicit | `devices.py:585`; `LiveDashboardService.get_dashboard_summary` |
| `GET` | `/api/v1/devices/dashboard/fleet-snapshot` | Paginated fleet snapshot | Yes | tenant/plant-scoped | `page`, `page_size`, `plant_id?`, `sort`, `runtime_filter?`, `runtime_status?`, `operational_status?` | none | `FleetSnapshotResponse` | none explicit | `devices.py:610`; `LiveDashboardService.get_fleet_snapshot` |
| `GET` | `/api/v1/devices/internal/active-tenant-ids` | List tenant IDs with active devices | Yes | internal service only (`request.state.role == internal_service`) | none | none | `{ tenant_ids: string[] }` | `403 INTERNAL_SERVICE_REQUIRED` | `devices.py:643`; direct DB query |
| `GET` | `/api/v1/devices/dashboard/fleet-stream` | SSE fleet stream | Yes | tenant/plant-scoped | `page_size`, `plant_id?`, `runtime_status?`, `operational_status?`, `last_event_id?` plus `Last-Event-ID` header | none | `text/event-stream` | none explicit | `devices.py:667`; `fleet_stream_broadcaster`, `LiveDashboardService` |
| `GET` | `/api/v1/devices/{device_id}/dashboard-bootstrap` | Per-device dashboard bootstrap | Yes | device must exist and be in scope | `device_id` | none | `DeviceDashboardBootstrapResponse` | `404 DEVICE_NOT_FOUND` | `devices.py:795`; `LiveDashboardService.get_dashboard_bootstrap` |
| `GET` | `/api/v1/devices/dashboard/today-loss-breakdown` | Fleet loss split by category/device | Yes | tenant/plant-scoped | `plant_id?` | none | `TodayLossBreakdownResponse` | none explicit | `devices.py:843`; `LiveDashboardService.get_today_loss_breakdown` |
| `GET` | `/api/v1/devices/calendar/monthly-energy` | Fleet monthly calendar summary | Yes | tenant-scoped | `year`, `month` | none | `MonthlyEnergyCalendarResponse` | none explicit | `devices.py:868`; `LiveDashboardService.get_monthly_energy_calendar` |
| `GET` | `/api/v1/devices/hardware-mappings` | Current device-to-hardware mappings | Yes | tenant/plant-scoped | `plant_id?`, `device_id?` | none | `DeviceHardwareMappingListResponse` | hardware errors mapped via `_raise_hardware_http_error` | `devices.py:892`; `HardwareInventoryService.list_current_device_mappings` |
| `GET` | `/api/v1/devices/{device_id}` | Get one device | Yes | tenant and plant scope enforced | `device_id` | none | `DeviceSingleResponse` | `404 DEVICE_NOT_FOUND`, `403 PLANT_ACCESS_DENIED` | `devices.py:940`; `DeviceService.get_device` |
| `GET` | `/api/v1/devices` | List devices | Yes | tenant-scoped; lower roles filtered to accessible plants | `plant_id?`, `device_type?`, `status?`, `page`, `page_size` | none | `DeviceListResponse` | `403 PLANT_ACCESS_DENIED` | `devices.py:1003`; `DeviceService.list_devices` |
| `POST` | `/api/v1/devices` | Create device | Yes | viewer forbidden; plant-scoped for plant_manager/operator | none | `DeviceCreate` | `DeviceSingleResponse` | `400 PLANT_REQUIRED`, `403 FORBIDDEN`, `403 PLANT_ACCESS_DENIED`, `409 DEVICE_ALREADY_EXISTS`, `503 DEVICE_ID_ALLOCATION_FAILED` | `devices.py:1062`; `DeviceService.create_device` |
| `POST` | `/api/v1/devices/hardware-units` | Create hardware unit | Yes | `_ensure_hardware_write_access` | none | `HardwareUnitCreate` | `HardwareUnitSingleResponse` | service-mapped hardware errors | `devices.py:1177`; `HardwareInventoryService.create_hardware_unit` |
| `GET` | `/api/v1/devices/hardware-units/list` | List hardware units | Yes | tenant/plant-scoped | `plant_id?`, `unit_type?`, `status?` | none | `HardwareUnitListResponse` | none explicit | `devices.py:1201`; `HardwareInventoryService.list_hardware_units` |
| `PUT` | `/api/v1/devices/hardware-units/{hardware_unit_id}` | Update hardware unit | Yes | hardware write access | `hardware_unit_id` | `HardwareUnitUpdate` | `HardwareUnitSingleResponse` | service-mapped hardware errors | `devices.py:1224`; `HardwareInventoryService.update_hardware_unit` |
| `POST` | `/api/v1/devices/{device_id}/hardware-installations` | Install hardware on device | Yes | hardware write access | `device_id` | `DeviceHardwareInstallationCreate` | `DeviceHardwareInstallationSingleResponse` | `404 DEVICE_NOT_FOUND` | `devices.py:1252`; `HardwareInventoryService.install_hardware` |
| `POST` | `/api/v1/devices/hardware-installations/{installation_id}/decommission` | Decommission installation | Yes | hardware write access | `installation_id` | `DeviceHardwareInstallationDecommission` | `DeviceHardwareInstallationSingleResponse` | hardware errors | `devices.py:1282`; `HardwareInventoryService.decommission_installation` |
| `GET` | `/api/v1/devices/{device_id}/hardware-installations/current` | List active installations for device | Yes | device scope enforced | `device_id` | none | `DeviceHardwareInstallationHistoryResponse` | `404 DEVICE_NOT_FOUND` | `devices.py:1304`; `HardwareInventoryService.list_current_device_installations` |
| `GET` | `/api/v1/devices/{device_id}/hardware-installations/history` | Installation history for device | Yes | device scope enforced | `device_id` | none | `DeviceHardwareInstallationHistoryResponse` | `404 DEVICE_NOT_FOUND` | `devices.py:1331`; `HardwareInventoryService.get_device_installation_history` |
| `GET` | `/api/v1/devices/hardware-installations/history` | Org-wide installation history | Yes | tenant/plant-scoped | `plant_id?`, `device_id?`, `hardware_unit_id?`, `state?` | none | `DeviceHardwareInstallationHistoryResponse` | `404 DEVICE_NOT_FOUND` | `devices.py:1358`; `HardwareInventoryService.list_installation_history` |
| `PUT` | `/api/v1/devices/{device_id}` | Update device | Yes | tenant/plant-scoped | `device_id` | `DeviceUpdate` | `DeviceSingleResponse` | `404 DEVICE_NOT_FOUND`, `400 PLANT_REQUIRED`, `403 PLANT_ACCESS_DENIED` | `devices.py:1398`; `DeviceService.update_device` |
| `DELETE` | `/api/v1/devices/{device_id}` | Delete device | Yes | tenant/plant-scoped | `device_id`, query `soft=true` default | none | `204` no body | `404 DEVICE_NOT_FOUND`, `403 PLANT_ACCESS_DENIED` | `devices.py:1501`; `DeviceService.delete_device` |
| `POST` | `/api/v1/devices/{device_id}/shifts` | Create shift | Yes | device write access | `device_id`, legacy `tenant_id?` query ignored in favor of context | `ShiftCreate` | `ShiftSingleResponse` | `404 DEVICE_NOT_FOUND`, `409 SHIFT_OVERLAP_CONFLICT`, validation 400 | `devices.py:1588`; `ShiftService.create_shift` |
| `GET` | `/api/v1/devices/{device_id}/shifts` | List device shifts | Yes | device scope enforced | `device_id` | none | `ShiftListResponse` | `404 DEVICE_NOT_FOUND` | `devices.py:1664`; `ShiftService.get_shifts_by_device` |
| `GET` | `/api/v1/devices/{device_id}/shifts/{shift_id}` | Get one shift | Yes | device scope enforced | `device_id`, `shift_id` | none | `ShiftSingleResponse` | `404 DEVICE_NOT_FOUND`, `404 SHIFT_NOT_FOUND` | `devices.py:1700`; `ShiftService.get_shift` |
| `PUT` | `/api/v1/devices/{device_id}/shifts/{shift_id}` | Update shift | Yes | device write access | `device_id`, `shift_id` | `ShiftUpdate` | `ShiftSingleResponse` | `404 DEVICE_NOT_FOUND`, `404 SHIFT_NOT_FOUND`, `409 SHIFT_OVERLAP_CONFLICT` | `devices.py:1749`; `ShiftService.update_shift` |
| `DELETE` | `/api/v1/devices/{device_id}/shifts/{shift_id}` | Delete shift | Yes | device write access | `device_id`, `shift_id` | none | `ShiftDeleteResponse` | `404 DEVICE_NOT_FOUND`, `404 SHIFT_NOT_FOUND` | `devices.py:1832`; `ShiftService.delete_shift` |
| `GET` | `/api/v1/devices/{device_id}/uptime` | Compute uptime from shifts | Yes | device scope enforced | `device_id` | none | `UptimeResponse` | `404 DEVICE_NOT_FOUND` | `devices.py:1900`; `ShiftService.calculate_uptime` |
| `GET` | `/api/v1/devices/{device_id}/performance-trends` | Materialized performance trends | Yes | tenant/device scope | `device_id`, `metric=health|uptime`, `range=30m|1h|6h|24h|7d|30d` | none | `PerformanceTrendResponse` | `401 MISSING_TENANT_SCOPE`, `404 DEVICE_NOT_FOUND` | `devices.py:1936`; `PerformanceTrendService.get_trends` |
| `POST` | `/api/v1/devices/{device_id}/health-config` | Create health parameter config | Yes | device write access | `device_id` | `ParameterHealthConfigCreate` | `ParameterHealthConfigSingleResponse` | `404 DEVICE_NOT_FOUND`, `409 HEALTH_CONFIG_DUPLICATE_PARAMETER` | `devices.py:1985`; `HealthConfigService.create_health_config` |
| `GET` | `/api/v1/devices/{device_id}/health-config` | List health configs | Yes | device scope enforced | `device_id` | none | `ParameterHealthConfigListResponse` | `404 DEVICE_NOT_FOUND` | `devices.py:2064`; `HealthConfigService.get_health_configs_by_device` |
| `GET` | `/api/v1/devices/{device_id}/health-config/validate-weights` | Validate config weight total | Yes | device scope enforced | `device_id` | none | `WeightValidationResponse` | `404 DEVICE_NOT_FOUND` | `devices.py:2100`; `HealthConfigService.validate_weights` |
| `GET` | `/api/v1/devices/{device_id}/health-config/{config_id}` | Get one health config | Yes | device scope enforced | `device_id`, `config_id` | none | `ParameterHealthConfigSingleResponse` | `404 DEVICE_NOT_FOUND`, `404 HEALTH_CONFIG_NOT_FOUND` | `devices.py:2135`; `HealthConfigService.get_health_config` |
| `PUT` | `/api/v1/devices/{device_id}/health-config/{config_id}` | Update health config | Yes | device write access | `device_id`, `config_id` | `ParameterHealthConfigUpdate` | `ParameterHealthConfigSingleResponse` | `404 DEVICE_NOT_FOUND`, `404 HEALTH_CONFIG_NOT_FOUND`, `409 HEALTH_CONFIG_DUPLICATE_PARAMETER` | `devices.py:2184`; `HealthConfigService.update_health_config` |
| `DELETE` | `/api/v1/devices/{device_id}/health-config/{config_id}` | Delete health config (idempotent) | Yes | device write access | `device_id`, `config_id` | none | `dict { success, message, config_id, deleted }` | `404 DEVICE_NOT_FOUND` | `devices.py:2269`; `HealthConfigService.delete_health_config` |
| `POST` | `/api/v1/devices/{device_id}/health-config/bulk` | Bulk create/update health configs | Yes | device write access | `device_id` | `list[ParameterHealthConfigCreate]` | `ParameterHealthConfigListResponse` | `404 DEVICE_NOT_FOUND`, `409 HEALTH_CONFIG_DUPLICATE_PARAMETER` | `devices.py:2333`; `HealthConfigService.bulk_create_or_update` |
| `POST` | `/api/v1/devices/{device_id}/health-score` | Compute health score from telemetry payload | Yes | tenant/device scoped | `device_id` | `TelemetryValues { values, machine_state? }` | `HealthScoreResponse` | `404 DEVICE_NOT_FOUND` by service path | `devices.py:2409`; `HealthConfigService.calculate_health_score` |
| `GET` | `/api/v1/devices/{device_id}/properties` | Get one device’s dynamic properties | Yes | tenant/device scoped | `device_id`, `numeric_only=true` | none | `list[DevicePropertyResponse]` | `404 DEVICE_NOT_FOUND` | `devices.py:2446`; `DevicePropertyService.get_device_properties` |
| `POST` | `/api/v1/devices/{device_id}/properties/sync` | Sync properties from telemetry | Yes | internal/telemetry path, but regular auth middleware still applies | `device_id` | ad-hoc `dict` telemetry body | `dict` | unknown device returns `success:false skipped:true` instead of 404 | `devices.py:2495`; `DevicePropertyService.sync_from_telemetry`, `DeviceService.update_last_seen` |
| `POST` | `/api/v1/devices/{device_id}/live-update` | Atomic low-latency live state update | Yes | internal/telemetry path | `device_id` | `DeviceLiveUpdateRequest` | `dict` | returns JSON `404 DEVICE_NOT_FOUND` for unknown device | `devices.py:2545`; `LiveProjectionService.apply_live_update` |
| `POST` | `/api/v1/devices/live-update/batch` | Batch live state update | Yes | internal/telemetry path | none | `DeviceLiveUpdateBatchRequest` | `dict { success, results[] }` | partial per-item errors; top-level raises on unexpected failure | `devices.py:2599`; `LiveProjectionService.apply_live_updates_batch` |
| `GET` | `/api/v1/devices/{device_id}/dashboard-widgets` | Get selected dashboard widgets | Yes | device scoped | `device_id` | none | `DashboardWidgetConfigResponse` | `404 device not found` | `devices.py:2713`; `DevicePropertyService.get_dashboard_widget_config` |
| `PUT` | `/api/v1/devices/{device_id}/dashboard-widgets` | Replace widget selection | Yes | device write access | `device_id` | `DashboardWidgetConfigUpdateRequest { selected_fields[] }` | `DashboardWidgetConfigResponse` | `404`, `422 invalid/unavailable fields` | `devices.py:2751`; `DevicePropertyService.replace_dashboard_widget_config` |
| `POST` | `/api/v1/devices/{device_id}/heartbeat` | Update last_seen/runtime status | Yes | tenant/device scoped | `device_id` | none | `dict { success, device_id, first_telemetry_timestamp, last_seen_timestamp, runtime_status }` | unknown device returns `success:false` | `devices.py:2801`; `DeviceService.update_last_seen` |
| `GET` | `/api/v1/devices/{device_id}/state-intervals` | List idle/overconsumption/runtime intervals | Yes | tenant/device scoped | `start_time?`, `end_time?`, `state_type?`, `is_open?`, `limit`, `offset` | none | `DeviceStateIntervalListResponse` | `400 invalid range`, `404 device not found` | `devices.py:2847`; `DeviceStateIntervalRepository.list_device_intervals` |
| `GET` | `/api/v1/devices/{device_id}/idle-config` | Get idle config | Yes | device scoped | `device_id` | none | `dict` | `404` | `devices.py:2898`; `IdleRunningService.get_idle_config` |
| `POST` | `/api/v1/devices/{device_id}/idle-config` | Set idle config | Yes | device write access | `device_id` | `IdleConfigRequest` | `dict` | `400 threshold validation`, `404` | `devices.py:2926`; `IdleRunningService.set_idle_config` |
| `GET` | `/api/v1/devices/{device_id}/current-state` | Get current runtime/load/waste state | Yes | device scoped | `device_id` | none | `dict` | `404` | `devices.py:2970`; `IdleRunningService.get_current_state` |
| `GET` | `/api/v1/devices/{device_id}/waste-config` | Get device waste config | Yes | device scoped | `device_id` | none | `dict` | `404` | `devices.py:2998`; `IdleRunningService.get_waste_config` |
| `PUT` | `/api/v1/devices/{device_id}/waste-config` | Set device waste config | Yes | device write access | `device_id` | `DeviceWasteConfigRequest` | `dict` | `400 threshold validation`, `404` | `devices.py:3026`; `IdleRunningService.set_waste_config` |
| `GET` | `/api/v1/devices/{device_id}/loss-stats` | Get device loss stats | Yes | device scoped | `device_id` | none | `dict` | `404` | `devices.py:3079`; `DashboardService.get_device_loss_stats` |
| `GET` | `/api/v1/devices/{device_id}/idle-stats` | Get idle stats | Yes | device scoped | `device_id` | none | `dict` | `404` | `devices.py:3108`; `IdleRunningService.get_idle_stats` |

Schema map for device-service:
- `DeviceCreate`, `DeviceUpdate`, `DeviceResponse`, `DeviceListResponse`, `DeviceSingleResponse`
- `HardwareUnitCreate`, `HardwareUnitUpdate`, `HardwareUnitResponse`, `DeviceHardwareInstallationCreate`, `DeviceHardwareInstallationDecommission`
- `ShiftCreate`, `ShiftUpdate`, `ShiftResponse`, `UptimeResponse`
- `ParameterHealthConfigCreate`, `ParameterHealthConfigUpdate`, `HealthScoreResponse`, `TelemetryValues`
- `DevicePropertyResponse`, `DashboardWidgetConfigUpdateRequest`, `DashboardSummaryResponse`, `FleetSnapshotResponse`, `DeviceDashboardBootstrapResponse`, `TodayLossBreakdownResponse`, `MonthlyEnergyCalendarResponse`
- file: `services/device-service/app/schemas/device.py`

### Data Service

Endpoint group refs:
- `services/data-service/src/main.py`
- `services/data-service/src/api/routes.py`
- `services/data-service/src/api/websocket.py`
- models: `services/data-service/src/models/telemetry.py`

Mounted REST prefix: `Confirmed from code` `settings.api_prefix`, default `/api/v1/data` (`services/data-service/src/config/settings.py:230`).

| Method | Full path | Purpose | Auth | Scope | Query / path | Body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `GET` | `/` | Root/info route | `Needs runtime verification` exact auth behavior; mounted in main | app-level | none | none | root JSON | none | `src/main.py:246` |
| `GET` | `/health` | Service health | No | public | none | none | health JSON | none | `src/main.py:256` |
| `GET` | `/api/v1/data/health` | Prefix-scoped health route | No | public | none | none | `HealthResponse` | none | `api/routes.py:91` |
| `GET` | `/api/v1/data/telemetry/{device_id}` | Query telemetry series | Yes | tenant required; lower roles filtered by plant | `device_id`, `start_time?`, `end_time?`, `fields?`, `aggregate?`, `interval?`, `limit` | none | `ApiResponse { success, data.items[], total, device_id }` using `TelemetryPoint.to_api_dict()` | `400 QUERY_WINDOW_TOO_WIDE`, `500 INTERNAL_ERROR` | `api/routes.py:111`; `TelemetryService.get_telemetry` |
| `GET` | `/api/v1/data/telemetry/{device_id}/latest` | Latest point | Yes | tenant/plant scoped | `device_id` | none | `ApiResponse { item?, device_id }` | `500 INTERNAL_ERROR` | `api/routes.py:183`; `TelemetryService.get_latest` |
| `GET` | `/api/v1/data/telemetry/{device_id}/earliest` | Earliest point after optional start | Yes | tenant/plant scoped | `device_id`, `start_time?` | none | `ApiResponse { item?, device_id }` | `500` | `api/routes.py:217`; `TelemetryService.get_earliest` |
| `POST` | `/api/v1/data/telemetry/latest-batch` | Latest point for many devices | Yes | tenant/plant scoped | none | `LatestBatchRequest { device_ids[] }` | `ApiResponse { items: {device_id: point|null}, total }` | `500` | `api/routes.py:253`; `TelemetryService.get_latest_batch` |
| `GET` | `/api/v1/data/stats/{device_id}` | Aggregate telemetry stats | Yes | tenant/plant scoped | `device_id`, `start_time?`, `end_time?` | none | `ApiResponse { data: TelemetryStats or dict }` | `404 NO_DATA`, `500` | `api/routes.py:295`; `TelemetryService.get_stats` |
| `POST` | `/api/v1/data/query` | Custom telemetry query wrapper | Yes | tenant/plant scoped | none | `TelemetryQuery { device_id, start_time?, end_time?, fields?, aggregate?, interval?, limit }` | `ApiResponse { items[], total }` | `500` | `api/routes.py:349`; `TelemetryService.get_telemetry` |
| `WS` | `/ws/telemetry/{device_id}` | Live telemetry websocket | `Needs runtime verification` auth path | device-specific subscription | `device_id` | websocket messages `ping` / `subscribe` | server sends `connected`, `heartbeat`, `telemetry`, `pong`, `subscribed` | closes with code `1008` when max connections reached | `api/websocket.py:193`; `ConnectionManager` |
| `GET` | `/ws/stats` | Websocket connection stats | `Needs runtime verification` auth path | ops | none | none | `{ total_connections, device_subscriptions, max_connections }` | none | `api/websocket.py:273` |

Shared REST DTOs:
- `TelemetryPoint`, `TelemetryQuery`, `TelemetryStats`, `ApiResponse`, `TelemetryListResponse`, `LatestBatchRequest`
- files: `services/data-service/src/models/telemetry.py`, `src/api/routes.py`

Defined but not obviously mounted:
- `services/data-service/src/api/telemetry.py` duplicates `/telemetry/{device_id}` and `/stats/{device_id}` but is not included in `src/main.py`.

### Energy Service

Endpoint refs:
- `services/energy-service/app/api/routes.py`
- schemas: `services/energy-service/app/schemas.py`

| Method | Full path | Purpose | Auth | Scope | Query / path | Body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `GET` | `/health` | Service health | No | public | none | none | `{ status, service }` | none | `app/main.py:26` |
| `GET` | `/api/v1/energy/health` | Prefix health | Yes if middleware applies to prefixed route; open-path skip may not include it | public-ish | none | none | `{ status, service }` | none | `routes.py:22` |
| `POST` | `/api/v1/energy/live-update` | Apply one live energy update | Yes | tenant from request or body `tenant_id` | none | `LiveUpdateRequest { telemetry, dynamic_fields?, normalized_fields?, tenant_id? }` | `{ success, data }` | returns `{ success:false, error }` when device_id missing | `routes.py:27`; `EnergyEngine.apply_live_update` |
| `POST` | `/api/v1/energy/live-update/batch` | Apply batch energy updates | Yes | tenant from request or body | none | `LiveUpdateBatchRequest { tenant_id?, updates[] }` | `{ success, results[] }` | none explicit | `routes.py:47`; `EnergyEngine.apply_live_updates_batch` |
| `POST` | `/api/v1/energy/device-lifecycle/{device_id}` | Update lifecycle status | Yes | internal/device scoped | `device_id` | `DeviceLifecycleRequest { status: running|stopped|restarted, at? }` | `{ success, data }` | none explicit | `routes.py:72`; `EnergyEngine.apply_device_lifecycle` |
| `GET` | `/api/v1/energy/summary` | Tenant energy summary | Yes | tenant-scoped | none | none | `{ success, ...payload }` | none explicit | `routes.py:80`; `EnergyEngine.get_summary` |
| `GET` | `/api/v1/energy/today-loss-breakdown` | Tenant loss breakdown | Yes | tenant-scoped | none | none | `{ success, ...payload }` | none explicit | `routes.py:86`; `EnergyEngine.get_today_loss_breakdown` |
| `GET` | `/api/v1/energy/calendar/monthly` | Monthly calendar summary | Yes | tenant-scoped + feature `calendar` | `year`, `month` | none | `{ success, ...payload }` | feature denial | `routes.py:92`; `EnergyEngine.get_monthly_calendar` |
| `GET` | `/api/v1/energy/device/{device_id}/range` | Device range summary | Yes | tenant/device scoped | `device_id`, `start_date`, `end_date` | none | `{ success, ...payload }`; backing schema `DeviceRangeResponse` | none explicit | `routes.py:103`; `EnergyEngine.get_device_range` |

### Rule Engine Service

Endpoint refs:
- `services/rule-engine-service/app/api/v1/router.py`
- `services/rule-engine-service/app/api/v1/rules.py`
- `services/rule-engine-service/app/api/v1/alerts.py`
- `services/rule-engine-service/app/api/v1/admin_notification_usage.py`
- schemas: `services/rule-engine-service/app/schemas/rule.py`, `schemas/telemetry.py`

#### Health / ops

| Method | Full path | Purpose | Auth | Handler |
|---|---|---|---|---|
| `GET` | `/health` | Liveness | No | `app/__init__.py:105` |
| `GET` | `/ready` | Readiness | No | `app/__init__.py:118` |
| `GET` | `/metrics` | Metrics | No | `app/__init__.py:148` |

#### Rule endpoints (`/api/v1/rules`)

| Method | Full path | Purpose | Auth | Scope / role | Params | Body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `GET` | `/api/v1/rules/{rule_id}` | Get rule | Yes | tenant + accessible devices | `rule_id` | none | `RuleSingleResponse` | `404 RULE_NOT_FOUND`, `503 DEVICE_SCOPE_UNAVAILABLE` | `rules.py:87`; `RuleService.get_rule` |
| `GET` | `/api/v1/rules` | List rules | Yes | tenant + accessible devices | `status?`, `device_id?`, `page`, `page_size` | none | `RuleListResponse` | `503 DEVICE_SCOPE_UNAVAILABLE` | `rules.py:126`; `RuleService.list_rules` |
| `POST` | `/api/v1/rules` | Create rule | Yes | tenant-scoped; device scope validated | none | `RuleCreate` | `RuleSingleResponse` | `403 RULE_SCOPE_FORBIDDEN`, `409 RULE_ALREADY_EXISTS`, `400 VALIDATION_ERROR` | `rules.py:164`; `RuleService.create_rule` |
| `PUT` | `/api/v1/rules/{rule_id}` | Update rule | Yes | tenant/device scope | `rule_id` | `RuleUpdate` | `RuleSingleResponse` | `403 RULE_SCOPE_FORBIDDEN`, `400 VALIDATION_ERROR`, `404 RULE_NOT_FOUND` | `rules.py:325`; `RuleService.update_rule` |
| `PATCH` | `/api/v1/rules/{rule_id}/status` | Change status | Yes | tenant/device scope | `rule_id` | `RuleStatusUpdate { status }` | `RuleStatusResponse` | `403 RULE_SCOPE_FORBIDDEN`, `404 RULE_NOT_FOUND` | `rules.py:388`; `RuleService.update_rule_status` |
| `DELETE` | `/api/v1/rules/{rule_id}` | Delete rule | Yes | tenant/device scope | `rule_id`, `soft=true` | none | `RuleDeleteResponse` | `403 RULE_SCOPE_FORBIDDEN`, `404 RULE_NOT_FOUND` | `rules.py:448`; `RuleService.delete_rule` |
| `POST` | `/api/v1/rules/evaluate` | Evaluate telemetry against active rules | Yes, typically internal `data-service` call | tenant required | none | `TelemetryPayload` from `schemas/rule.py` (dynamic fields, `device_id`, `timestamp`, etc.) | `{ rules_evaluated, rules_triggered, results }` | `400 EVALUATION_ERROR`, `500 INTERNAL_ERROR` | `rules.py:504`; `RuleEvaluator.evaluate_telemetry` |

#### Alert and activity endpoints (`/api/v1/alerts`)

| Method | Full path | Purpose | Auth | Scope | Params | Body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `GET` | `/api/v1/alerts` | List alerts | Yes | tenant + accessible devices | `device_id?`, `rule_id?`, `status?`, `page`, `page_size` | none | `AlertListResponse` | none explicit | `alerts.py:98`; `AlertRepository.list_alerts` |
| `PATCH` | `/api/v1/alerts/{alert_id}/acknowledge` | Acknowledge alert | Yes | tenant + accessible devices | `alert_id` | `AlertAcknowledgeRequest { acknowledged_by? }` | `AlertSingleResponse` | `404 ALERT_NOT_FOUND` | `alerts.py:143`; `AlertRepository.acknowledge_alert` |
| `PATCH` | `/api/v1/alerts/{alert_id}/resolve` | Resolve alert | Yes | tenant + accessible devices | `alert_id` | none | `AlertSingleResponse` | `404 ALERT_NOT_FOUND` | `alerts.py:212`; `AlertRepository.resolve_alert` |
| `GET` | `/api/v1/alerts/events` | List activity events | Yes | tenant + accessible devices | `device_id?`, `event_type?`, `page`, `page_size` | none | `ActivityEventListResponse` | none explicit | `alerts.py:272`; `ActivityEventRepository.list_events` |
| `GET` | `/api/v1/alerts/events/unread-count` | Get unread count | Yes | tenant + accessible devices | `device_id?` | none | `ActivityUnreadCountResponse` | none | `alerts.py:304`; `ActivityEventRepository.unread_count` |
| `PATCH` | `/api/v1/alerts/events/mark-all-read` | Mark events read | Yes | tenant + accessible devices | `device_id?` | none | `ActivityActionResponse` | none | `alerts.py:320`; `ActivityEventRepository.mark_all_read` |
| `DELETE` | `/api/v1/alerts/events` | Clear history | Yes | tenant + accessible devices | `device_id?` | none | `ActivityActionResponse` | none | `alerts.py:337`; `ActivityEventRepository.clear_history` |
| `GET` | `/api/v1/alerts/events/summary` | Dashboard summary | Yes | tenant + accessible devices | none | none | `ActivitySummaryResponse` | none | `alerts.py:354`; activity + alert repositories |

#### Super-admin notification usage (`/api/v1/admin/notification-usage`)

| Method | Full path | Purpose | Auth | Scope | Params | Response | Handler / service |
|---|---|---|---|---|---|---|---|
| `GET` | `/api/v1/admin/notification-usage/{tenant_id}/summary` | Monthly usage summary | Yes | `super_admin` only | `month`, filters `channel?`, `status?`, `rule_id?`, `device_id?`, `date_from?`, `date_to?`, `search?` | `NotificationUsageSummaryResponse` | `admin_notification_usage.py:113`; `NotificationDeliveryAuditService.summarize_month` |
| `GET` | `/api/v1/admin/notification-usage/{tenant_id}/logs` | Paged usage logs | Yes | `super_admin` only | above filters plus `include_metadata`, `page`, `page_size` | `NotificationUsageLogsResponse` | `admin_notification_usage.py:174`; `NotificationDeliveryAuditService.list_month_logs` |
| `GET` | `/api/v1/admin/notification-usage/{tenant_id}/export.csv` | CSV export | Yes | `super_admin` only | same filters | `text/csv` stream | `admin_notification_usage.py:245`; `NotificationDeliveryAuditService.stream_month_logs_csv` |

### Analytics Service

Endpoint refs:
- `services/analytics-service/src/main.py`
- `services/analytics-service/src/api/routes/analytics.py`
- `services/analytics-service/src/api/routes/health.py`
- schemas: `services/analytics-service/src/models/schemas.py`

| Method | Full path | Purpose | Auth | Scope | Params | Body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `GET` | `/health` | Top-level health | No | public | none | none | health JSON | none | `main.py:212` |
| `GET` | `/health/live` | Liveness | No | public | none | none | `HealthResponse` | none | `health.py:25` |
| `GET` | `/health/ready` | Readiness | No | public | none | none | `ReadinessResponse` | none | `health.py:35` |
| `POST` | `/api/v1/analytics/run` | Submit single-device analytics job | Yes | tenant/device scoped | none | `AnalyticsRequest { device_id, dataset_key?, start_time?, end_time?, analysis_type, model_name, parameters? }` | `AnalyticsJobResponse { job_id, status, message }` | `503 WORKER_UNAVAILABLE`, `401 MISSING_AUTH_CONTEXT`, admission-control `429/503` | `analytics.py:151`; queue + `ResultRepository.create_job` |
| `POST` | `/api/v1/analytics/run-fleet` | Submit fleet parent job | Yes | tenant/device scoped | none | `FleetAnalyticsRequest { device_ids[], start_time, end_time, analysis_type, model_name?, parameters? }` | `AnalyticsJobResponse` | `503 WORKER_UNAVAILABLE`, `400 NO_ACCESSIBLE_DEVICES`, admission-control `429/503` | `analytics.py:252`; queue + `ResultRepository.create_job` |
| `GET` | `/api/v1/analytics/status/{job_id}` | Job status | Yes | tenant/device scoped | `job_id` | none | `JobStatusResponse` | `404 job not found` | `analytics.py:349`; `ResultRepository.get_job_scoped` |
| `GET` | `/api/v1/analytics/results/{job_id}` | Completed job results | Yes | tenant/device scoped | `job_id` | none | `AnalyticsResultsResponse` | `400 not completed`, `404 job not found` | `analytics.py:389`; `ResultRepository.get_job_scoped` |
| `GET` | `/api/v1/analytics/models` | Supported model list | Yes | feature access only | none | none | `SupportedModelsResponse` | none | `analytics.py:441` |
| `GET` | `/api/v1/analytics/jobs` | List jobs | Yes | tenant/device scoped | `status?`, `device_id?`, `limit`, `offset` | none | `list[JobStatusResponse]` | none explicit | `analytics.py:503`; `ResultRepository.list_jobs` |
| `GET` | `/api/v1/analytics/ops/queue` | Queue ops snapshot | Yes | authenticated ops endpoint; no explicit role gate in handler | none | none | ops JSON | none explicit | `analytics.py:530`; result repo + worker heartbeat query |
| `POST` | `/api/v1/analytics/labels/failure-events` | Persist failure labels | Yes | no explicit tenant guard in handler beyond middleware | none | ad-hoc JSON requiring `device_id`, `event_time` | `{ status, id }` | `422` missing/invalid event_time | `analytics.py:583`; inserts `FailureEventLabel` |
| `POST` | `/api/v1/analytics/accuracy/evaluate` | Run accuracy backtest | Yes | authenticated | query `device_id?`, `lookback_days`, `lead_window_hours` | none | evaluation JSON | none explicit | `analytics.py:616`; `AccuracyEvaluator.evaluate_failure_predictions` |
| `GET` | `/api/v1/analytics/accuracy/latest` | Latest accuracy record | Yes | authenticated | `device_id?` | none | accuracy summary JSON or `{ status: no_evaluation }` | none explicit | `analytics.py:637` |
| `GET` | `/api/v1/analytics/datasets` | List exported datasets for device | Yes | authenticated | `device_id` | none | `{ device_id, datasets[] }` | none explicit | `analytics.py:674`; `DatasetService.list_available_datasets` |
| `GET` | `/api/v1/analytics/retrain-status` | Last auto-retrain status | Yes | authenticated | none | none | `dict` | none | `analytics.py:697`; app retrainer state |
| `GET` | `/api/v1/analytics/formatted-results/{job_id}` | Dashboard-ready formatted results | Yes | tenant scoped | `job_id` | none | `dict` | `400 job not completed`, `404 missing formatted results` | `analytics.py:706`; `ResultRepository.get_job_scoped` |

### Reporting Service

Endpoint refs:
- `services/reporting-service/src/main.py`
- `services/reporting-service/src/handlers/energy_reports.py`
- `services/reporting-service/src/handlers/comparison_reports.py`
- `services/reporting-service/src/handlers/report_common.py`
- `services/reporting-service/src/handlers/settings.py`
- `services/reporting-service/src/handlers/tariffs.py`
- schemas: `services/reporting-service/src/schemas/requests.py`, `responses.py`

#### Ops

| Method | Full path | Purpose | Auth | Handler |
|---|---|---|---|---|
| `GET` | `/health` | Liveness | No | `main.py:168` |
| `GET` | `/ready` | Readiness | No | `main.py:173` |
| `GET` | `/metrics` | Reporting queue metrics | No | `main.py:223` |

#### Report creation and lifecycle

| Method | Full path | Purpose | Auth | Scope | Params | Body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `POST` | `/api/reports/energy/consumption` | Submit energy consumption report | Yes | feature `reports`; tenant required | none | `ConsumptionReportRequest { start_date, end_date, device_id, report_name?, tenant_id? }` | `ReportResponse` | `400 VALIDATION_ERROR`, `400 NO_VALID_DEVICES`, `403 TENANT_SCOPE_REQUIRED`, downstream device scope `503/502` | `energy_reports.py:137`; `ReportRepository.create_report`, report queue enqueue |
| `POST` | `/api/reports/energy/comparison` and `/api/reports/energy/comparison/` | Submit comparison report | Yes | feature `reports`; tenant required | none | `ComparisonReportRequest` | `ReportResponse` | `403 TENANT_SCOPE_REQUIRED`, `400` comparison validation | `comparison_reports.py:37`; `ReportRepository.create_report` |
| `GET` | `/api/reports/history` | List report history | Yes | feature `reports`; tenant/device scoped | `tenant_id?`, `limit`, `offset`, `report_type?` | none | `{ reports[] }` | tenant/device scope errors | `report_common.py:79`; `ReportRepository.list_reports` |
| `POST` | `/api/reports/schedules` | Create scheduled report | Yes | feature `reports`; tenant/device scoped | `tenant_id?` | `ScheduleCreateRequest { report_type, frequency, params_template }` | schedule JSON | `403 SCHEDULE_SCOPE_FORBIDDEN`, `400 VALIDATION_ERROR` | `report_common.py:113`; `ScheduledRepository.create_schedule` |
| `GET` | `/api/reports/schedules` | List schedules | Yes | feature `reports`; tenant/device scoped | `tenant_id?` | none | `{ schedules[] }` | none explicit | `report_common.py:159`; `ScheduledRepository.list_schedules` |
| `DELETE` | `/api/reports/schedules/{schedule_id}` | Deactivate schedule | Yes | feature `reports`; tenant/device scoped | `schedule_id`, `tenant_id?` | none | `{ message }` | `404 Schedule not found`, `403 Access denied` | `report_common.py:189`; `ScheduledRepository.update_schedule` |
| `GET` | `/api/reports/{report_id}/status` | Report job status | Yes | feature `reports`; tenant/device scoped | `report_id`, `tenant_id?` | none | `{ report_id, status, progress, error_code, error_message }` | `404 Report not found` | `report_common.py:212`; `ReportRepository.get_report` |
| `GET` | `/api/reports/{report_id}/result` | Get report result JSON | Yes | feature `reports`; tenant/device scoped | `report_id`, `tenant_id?` | none | report `result_json` | `404 Report not found`, `404 Report not completed yet` | `report_common.py:236`; `ReportRepository.get_report` |
| `GET` | `/api/reports/{report_id}/download` | Download report PDF | Yes | feature `reports`; tenant/device scoped | `report_id`, `tenant_id?` | none | `application/pdf` stream | `404 Report not found`, `404 PDF not available`, `404 PDF_NOT_FOUND` | `report_common.py:257`; `minio_client.download_pdf` |

#### Tariff/settings endpoints

| Method | Full path | Purpose | Auth | Scope | Body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|
| `POST` | `/api/reports/tariffs/` | Create/update full tariff row | Yes | feature `reports`; tenant required | `TariffRequest { tenant_id, energy_rate_per_kwh, demand_charge_per_kw, reactive_penalty_rate, fixed_monthly_charge, power_factor_threshold, currency }` | `TariffResponse` | tenant scope errors | `tariffs.py:19`; `TariffRepository.upsert_tariff` |
| `GET` | `/api/reports/tariffs/{tenant_id}` | Get tariff by tenant | Yes | feature `reports`; tenant scope resolved from request/header/path | none | `TariffResponse` | `404 Tariff not found for tenant` | `tariffs.py:44`; `TariffRepository.get_tariff` |
| `GET` | `/api/v1/settings/tariff` | Lightweight current tariff | Yes | feature `settings`; tenant required | none | `{ rate, currency, updated_at }` | none; returns null rate if missing | `settings.py:45`; `TariffRepository.get_tariff` |
| `POST` | `/api/v1/settings/tariff` | Upsert lightweight tariff | Yes | feature `settings`; tenant required | `TariffUpsertRequest { rate, currency, updated_by? }` | `{ rate, currency, updated_at }` | `400 VALIDATION_ERROR` for currency | `settings.py:62`; `TariffRepository.upsert_tariff` |
| `GET` | `/api/v1/settings/notifications` | List active notification channels | Yes | feature `settings`; tenant required | none | `{ email: [...], whatsapp: [], sms: [] }` | none | `settings.py:88`; `SettingsRepository.list_active_channels` |
| `POST` | `/api/v1/settings/notifications/email` | Add email channel | Yes | feature `settings`; tenant required | `NotificationEmailRequest { email }` | `{ id, value, is_active }` | validation errors | `settings.py:105`; `SettingsRepository.add_email_channel` |
| `DELETE` | `/api/v1/settings/notifications/email/{channel_id}` | Disable email channel | Yes | feature `settings`; tenant required | none | `{ success, id }` | `404 NOT_FOUND` | `settings.py:116`; `SettingsRepository.disable_email_channel` |

### Waste Analysis Service

Endpoint refs:
- `services/waste-analysis-service/src/main.py`
- `services/waste-analysis-service/src/handlers/waste_analysis.py`
- schemas: `services/waste-analysis-service/src/schemas/waste.py`

| Method | Full path | Purpose | Auth | Scope | Params | Body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|---|
| `GET` | `/health` | Liveness | No | public | none | none | health JSON | none | `main.py:158` |
| `GET` | `/ready` | Readiness | No | public | none | none | readiness JSON | none | `main.py:163` |
| `POST` | `/api/v1/waste/analysis/run` | Start waste-analysis job | Yes | feature `waste_analysis`; tenant required | none | `WasteAnalysisRunRequest { job_name?, scope, device_ids?, start_date, end_date, granularity }` | `WasteAnalysisRunResponse` | `400 VALIDATION_ERROR`, duplicate returns existing job info | `waste_analysis.py:64`; `WasteRepository.create_job`, background task |
| `GET` | `/api/v1/waste/analysis/{job_id}/status` | Job status | Yes | tenant-scoped | `job_id` | none | `WasteStatusResponse` | `404 Job not found` | `waste_analysis.py:123`; `WasteRepository.get_job` |
| `GET` | `/api/v1/waste/analysis/{job_id}/result` | Job result JSON | Yes | tenant-scoped | `job_id` | none | raw `result_json` | `404 Job not found`, `400 Result not available` | `waste_analysis.py:141`; `WasteRepository.get_job` |
| `GET` | `/api/v1/waste/analysis/{job_id}/download` | Download metadata URL | Yes | tenant-scoped | `job_id` | none | `WasteDownloadResponse` | `404 Job not found`, `404 Report file not available` | `waste_analysis.py:154` |
| `GET` | `/api/v1/waste/analysis/{job_id}/file` | Stream PDF file | Yes | tenant-scoped | `job_id` | none | `application/pdf` stream | `404 Job not found`, `404 Report file not available` | `waste_analysis.py:171`; `minio_client.download_pdf` |
| `GET` | `/api/v1/waste/analysis/history` | List past jobs | Yes | tenant-scoped | `limit`, `offset` | none | `WasteHistoryResponse` | none explicit | `waste_analysis.py:195`; `WasteRepository.list_jobs` |

### Copilot Service

Endpoint refs:
- `services/copilot-service/src/main.py`
- `services/copilot-service/src/api/chat.py`
- response DTOs: `services/copilot-service/src/response/schema.py`

| Method | Full path | Purpose | Auth | Scope | Body | Response | Key errors / behavior | Handler / service |
|---|---|---|---|---|---|---|---|---|
| `GET` | `/health` | Liveness | No | public | none | health JSON | none | `main.py:86` |
| `GET` | `/ready` | Readiness incl. provider/schema/db state | No | public | none | readiness JSON | none | `main.py:98` |
| `POST` | `/api/v1/copilot/chat` | Ask copilot question | Yes | feature `copilot`; tenant required | `ChatRequest { message, conversation_history[], curated_context? }` | `CopilotResponse { answer, reasoning, reasoning_sections?, data_table?, chart?, page_links?, follow_up_suggestions[], curated_context?, error_code? }` | returns modeled error payload with `error_code=NOT_CONFIGURED|AI_UNAVAILABLE|INTERNAL_ERROR` rather than raising HTTP errors | `chat.py:31`; `CopilotEngine.process_question` |
| `GET` | `/api/v1/copilot/curated-questions` | Starter questions | Yes | feature `copilot` mounted router dependency | none | `CuratedQuestionsResponse { starter_questions[] }` | none | `chat.py:69`; `get_starter_questions()` |

### Data Export Service

Endpoint refs:
- `services/data-export-service/main.py`

| Method | Full path | Purpose | Auth | Scope | Params / body | Response | Key errors | Handler / service |
|---|---|---|---|---|---|---|---|---|
| `GET` | `/health` | Liveness | No | public | none | `HealthResponse` | none | `main.py:138` |
| `GET` | `/ready` | Readiness with worker/checkpoint/S3 checks | No | public | none | `ReadyResponse` | `503 { ready:false, checks }` | `main.py:149` |
| `POST` | `/api/v1/exports/run` | Trigger full or range export | Yes | tenant required; device scope enforced | `ExportRequest { device_id?, start_time?, end_time?, request_id? }` | `{ status: accepted, device_id?, device_ids?, request_id?, mode, start_time?, end_time? }` | `503 Export worker is not running`, `422 VALIDATION_ERROR`, `404 NO_EXPORTABLE_DEVICES`, `500 EXPORT_TRIGGER_FAILED` | `main.py:172`; `ExportWorker.force_export` |
| `GET` | `/api/v1/exports/status/{device_id}` | Export status by device | Yes | tenant/device scoped | `device_id` | status JSON from exporter | `503`, `404 DEVICE_NOT_FOUND` | `main.py:270`; `_worker.exporter.get_export_status` |

## 3. Internal Service-to-Service Endpoints

| Caller | Callee | Endpoint | Purpose | Auth / trust model | Source |
|---|---|---|---|---|---|
| `data-service` | `device-service` | `GET /api/v1/devices/{device_id}` | metadata enrichment for telemetry | `Confirmed from code`: internal headers via `build_internal_headers("data-service", tenant_id)` | `services/data-service/src/services/enrichment_service.py:215` |
| `data-service` | `rule-engine-service` | `POST /api/v1/rules/evaluate` | evaluate rules on telemetry | internal headers with tenant | `services/data-service/src/services/rule_engine_client.py:137` |
| `data-service` | `device-service` | `POST /api/v1/devices/live-update/batch` | projection sync batch | internal headers with tenant | `services/data-service/src/services/device_projection_client.py:184` |
| `data-service` | `device-service` | `POST /api/v1/devices/{device_id}/live-update` | single live update relay | internal headers with tenant | `services/data-service/src/services/outbox_relay.py:302-303` |
| `data-service` | `energy-service` | `POST /api/v1/energy/live-update` | single energy projection relay | internal headers with tenant | `services/data-service/src/services/outbox_relay.py:317-318` |
| `data-service` | `energy-service` | `POST /api/v1/energy/live-update/batch` | batched energy relay | internal headers with tenant | `services/data-service/src/services/outbox_relay.py:356-357` |
| `data-service` | `device-service` | `GET /api/v1/devices/{device_id}` | reconciliation/device lookup | internal headers with tenant | `services/data-service/src/services/outbox_relay.py:454-455` |
| `data-service` | `device-service` | `GET /api/v1/devices/dashboard/fleet-snapshot` | reconciliation drift check | internal headers | `services/data-service/src/services/reconciliation.py:203` |
| `data-service` | `device-service` | `GET /api/v1/devices/internal/active-tenant-ids` | discover tenant set for reconciliation | internal service auth only | `services/data-service/src/services/reconciliation.py:238` |
| `analytics-service` | `data-export-service` | `POST /api/v1/exports/run` | trigger export readiness | internal service URL; tenant auth depends on caller context or internal headers in orchestrator path | `services/analytics-service/src/services/readiness_orchestrator.py:97` |
| `analytics-service` | `data-export-service` | `GET /api/v1/exports/status/{device_id}` | poll export status | same | `services/analytics-service/src/services/readiness_orchestrator.py:197` |
| `analytics-service` | `data-service` | `GET /api/v1/data/telemetry/{device_id}` | fetch datasets/telemetry fallback | service URL | `services/analytics-service/src/services/dataset_service.py:253` |
| `analytics-service` | `device-service` | `GET /api/v1/devices/{device_id}` and `GET /api/v1/devices` | device scope and metadata | service URL | `services/analytics-service/src/services/dataset_service.py:336`, `src/services/device_scope.py:46` |
| `reporting-service` | `device-service` | `GET /api/v1/devices` | resolve accessible devices | internal headers/tenant context | `services/reporting-service/src/services/device_scope.py:51` |
| `reporting-service` | `device-service` | `GET /api/v1/devices/{device_id}` | validate/report device metadata | internal headers/tenant context | `services/reporting-service/src/services/device_scope.py:121` |
| `reporting-service` | `energy-service` | `GET /api/v1/energy/device/{device_id}/range` | pull energy totals for report task | internal tenant-scoped call | `services/reporting-service/src/tasks/report_task.py:93` |
| `reporting-service` | `device-service` | `GET /api/v1/devices/{device_id}/shifts` | pull shift config for reports | internal tenant-scoped call | `services/reporting-service/src/tasks/report_task.py:433` |
| `reporting-service` | `device-service` | `GET /api/v1/devices`, `GET /api/v1/devices/{device_id}` | report-task metadata/device selection | internal tenant-scoped call | `services/reporting-service/src/tasks/report_task.py:606`, `663`, `1088`, `1092` |
| `waste-analysis-service` | `device-service` | `GET /api/v1/devices` | list devices | internal headers plus `X-Tenant-Id` | `services/waste-analysis-service/src/services/remote_clients.py` |
| `waste-analysis-service` | `device-service` | `GET /api/v1/devices/{device_id}` | fetch one device | same | `remote_clients.py` |
| `waste-analysis-service` | `device-service` | `GET /api/v1/devices/{device_id}/shifts` | shift config | same | `remote_clients.py` |
| `waste-analysis-service` | `device-service` | `GET /api/v1/devices/{device_id}/idle-config` | idle thresholds | same | `remote_clients.py` |
| `waste-analysis-service` | `device-service` | `GET /api/v1/devices/{device_id}/waste-config` | waste thresholds | same | `remote_clients.py` |
| `waste-analysis-service` | `device-service` | `GET /api/v1/settings/waste-config` | site default waste config | same | `remote_clients.py` |
| `waste-analysis-service` | `energy-service` | `GET /api/v1/energy/device/{device_id}/range` | energy range data | same | `remote_clients.py` |
| `waste-analysis-service` | `reporting-service` | `GET /api/reports/history`, `GET /api/reports/{report_id}/result` | cross-check reporting reference kWh | internal headers + tenant header | `services/waste-analysis-service/src/tasks/waste_task.py` |
| `copilot-service` | `reporting-service` | `GET /api/v1/settings/tariff` | get current tariff | internal headers via shared tariff client | `services/copilot-service/src/integrations/service_clients.py`, `services/shared/tariff_client.py` |
| `waste-analysis-service` | `reporting-service` | `GET /api/v1/settings/tariff` | get current tariff | internal headers via shared tariff client | `remote_clients.py`, `services/shared/tariff_client.py` |
| `energy-service` | `device-service` | `GET /api/v1/devices` | device metadata/list for energy summary | internal call | `services/energy-service/app/services/energy_engine.py:135` |
| `energy-service` | `device-service` | `GET /api/v1/devices/{device_id}/loss-stats` | merge loss stats | internal call | `energy_engine.py:162` |
| `energy-service` | `device-service` | `GET /api/v1/devices/dashboard/summary` | combine dashboard summary | internal call | `energy_engine.py:196` |
| `energy-service` | `device-service` | `GET /api/v1/devices/{device_id}`, `/idle-config`, `/waste-config`, `/shifts` | device metadata/config hydration | internal call | `services/energy-service/app/services/device_meta.py:65-135` |

## 4. Webhook / Callback Endpoints

- `Not found in repository`: no inbound third-party webhook routes were found in the scanned API files.
- `Confirmed from code`: several “callback-like” internal ingestion endpoints exist, but they are not public third-party webhooks:
  - `POST /api/v1/devices/{device_id}/live-update`
  - `POST /api/v1/devices/live-update/batch`
  - `POST /api/v1/energy/live-update`
  - `POST /api/v1/energy/live-update/batch`
  - `POST /api/v1/rules/evaluate`

## 5. Realtime / Polling Interfaces

| Interface | Endpoint | Style | Purpose | Source |
|---|---|---|---|---|
| Fleet stream | `/api/v1/devices/dashboard/fleet-stream` | SSE | live fleet/device dashboard updates | `services/device-service/app/api/v1/devices.py:667` |
| Device telemetry websocket | `/ws/telemetry/{device_id}` | WebSocket | live telemetry push | `services/data-service/src/api/websocket.py:193` |
| Websocket stats | `/ws/stats` | polling GET | observe websocket load | `services/data-service/src/api/websocket.py:273` |
| Device dashboard bootstrap | `/api/v1/devices/{device_id}/dashboard-bootstrap` | polling/bootstrap GET | initial state before live stream | `devices.py:795` |
| Fleet snapshot | `/api/v1/devices/dashboard/fleet-snapshot` | polling GET | current fleet page view | `devices.py:610` |
| Dashboard summary | `/api/v1/devices/dashboard/summary` | polling GET | home dashboard cards | `devices.py:585` |
| Analytics job status | `/api/v1/analytics/status/{job_id}` | polling GET | job lifecycle | `analytics.py:349` |
| Report status | `/api/reports/{report_id}/status` | polling GET | report lifecycle | `report_common.py:212` |
| Waste job status | `/api/v1/waste/analysis/{job_id}/status` | polling GET | waste-analysis lifecycle | `waste_analysis.py:123` |
| Export status | `/api/v1/exports/status/{device_id}` | polling GET | export readiness | `data-export-service/main.py:270` |
| Latest telemetry | `/api/v1/data/telemetry/{device_id}/latest` | polling GET | latest point for dashboard/card refresh | `api/routes.py:183` |
| Latest telemetry batch | `/api/v1/data/telemetry/latest-batch` | polling POST | batch card refresh across devices | `api/routes.py:253` |
| Energy summary | `/api/v1/energy/summary` | polling GET | energy dashboard summary | `energy/routes.py:80` |

## 6. API Contracts and Shared Types

### Shared auth / tenant contract

- `Confirmed from code`: tenant routing headers:
  - `X-Internal-Service`
  - `X-Tenant-Id`
  - `X-Target-Tenant-Id`
  - source: `services/shared/tenant_context.py`
- `Confirmed from code`: JWT access claims include `sub`, `email`, `tenant_id`, `role`, `plant_ids`, `permissions_version`, `tenant_entitlements_version`, `jti`.
- `Confirmed from code`: web refresh uses HttpOnly cookie rotation; mobile codepaths also support explicit refresh token submission. Source of record for token storage remains auth-service plus frontend/mobile clients, summarized in [memory.md](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory.md#8-authentication-and-authorization).

### Shared telemetry contract

- `Confirmed from code`: public telemetry points use `TelemetryPoint.to_api_dict()` and intentionally expose:
  - `timestamp`
  - `device_id`
  - `schema_version`
  - `enrichment_status`
  - numeric telemetry extras only
  - source: `services/data-service/src/models/telemetry.py`

### Shared feature entitlements contract

- `Confirmed from code`: auth `/me` and tenant entitlement APIs return:
  - `premium_feature_grants`
  - `role_feature_matrix`
  - `baseline_features_by_role`
  - `effective_features_by_role`
  - `available_features`
  - `entitlements_version`
  - sources: `services/auth-service/app/schemas/auth.py`, `services/shared/feature_entitlements.py`

### Shared physical-table note

- `Confirmed from code`: `notification_channels` is one shared physical table owned by reporting-service schema/migrations and read by rule-engine through the mirror model `NotificationChannelSetting`, not a second rule-engine table.
- Cross-reference: [memory-appendix-db.md#notification_channels](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md), [memory-appendix-db.md#rule-engine-service-schemas](/Users/vedanthshetty/Desktop/GIT-Testing/FactoryOPS-Cittagent-Obeya-main/memory-appendix-db.md)

### Rule contracts

- `Confirmed from code` key enums in `services/rule-engine-service/app/schemas/rule.py`:
  - `RuleStatus`: `active`, `paused`, `archived`
  - `RuleScope`: `all_devices`, `selected_devices`
  - `RuleType`: `threshold`, `time_based`, `continuous_idle_duration`
  - `NotificationChannel`: `email`, `sms`, `whatsapp`

### Analytics contracts

- `Confirmed from code` key DTOs in `services/analytics-service/src/models/schemas.py`:
  - `AnalyticsRequest`
  - `FleetAnalyticsRequest`
  - `AnalyticsJobResponse`
  - `JobStatusResponse`
  - `AnalyticsResultsResponse`
  - `SupportedModelsResponse`

### Reporting contracts

- `Confirmed from code` key DTOs in `services/reporting-service/src/schemas/requests.py` and `responses.py`:
  - `ConsumptionReportRequest`
  - `ComparisonReportRequest`
  - `TariffRequest`
  - `ReportResponse`
  - `TariffResponse`

### Waste contracts

- `Confirmed from code` key DTOs in `services/waste-analysis-service/src/schemas/waste.py`:
  - `WasteAnalysisRunRequest`
  - `WasteAnalysisRunResponse`
  - `WasteStatusResponse`
  - `WasteDownloadResponse`
  - `WasteHistoryResponse`

### Copilot contracts

- `Confirmed from code` key DTOs in `services/copilot-service/src/response/schema.py`:
  - `ChatRequest`
  - `CopilotResponse`
  - `CuratedQuestionsResponse`
  - nested types `ReasoningSections`, `DataTable`, `Chart`, `PageLink`

## 7. API Risk Areas

| Area | Why sensitive | Endpoints / files |
|---|---|---|
| Auth refresh and cookie handling | web uses cookie-scoped refresh; mobile uses body token; origin checks can easily regress | `POST /api/v1/auth/login`, `/refresh`, `/logout` in `services/auth-service/app/api/v1/auth.py` |
| Tenant switching | super-admin can select target tenant via header; easy to leak cross-tenant data if a service ignores shared tenant context | `/api/v1/auth/me`, all tenant-scoped services, `services/shared/auth_middleware.py`, `services/shared/tenant_context.py` |
| Internal-only device-service endpoint | `/internal/active-tenant-ids` trusts `internal_service` role state; should not become browser-accessible | `services/device-service/app/api/v1/devices.py:643` |
| Telemetry/public contract stability | dashboards and analytics depend on exact field names and response shape; `TelemetryPoint.to_api_dict()` intentionally suppresses extras | `services/data-service/src/api/routes.py`, `src/models/telemetry.py` |
| Live-update internal endpoints | used by telemetry pipeline; partial failures and retryability are encoded in ad-hoc JSON rather than strict DTOs | device `/live-update`, `/live-update/batch`; energy `/live-update`, `/live-update/batch` |
| Rule evaluation endpoint | internal request body is dynamic telemetry payload, easy to break by renaming normalized/projected fields | `POST /api/v1/rules/evaluate` in `rules.py`; called from `data-service` |
| Report and waste result/download routes | object-storage key presence and tenant scoping must stay aligned | `report_common.py`, `waste_analysis.py` |
| Analytics ops endpoints | queue metrics and label ingestion endpoints are mounted on same authenticated surface; role restrictions are minimal in handler code | `analytics.py:530`, `583`, `616`, `637` |
| Ad-hoc JSON bodies | several endpoints do not use explicit DTOs, making change detection weaker | `POST /api/v1/devices/properties/common`, `POST /api/v1/devices/{device_id}/properties/sync`, several summary/settings responses |
| Duplicate/legacy route modules | `data-service/src/api/telemetry.py` and empty `rule-engine evaluation.py` can confuse route discovery and future edits | noted above |
