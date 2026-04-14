# API Documentation

This document is auto-generated from the codebase. Last updated: 2026-04-02

## 1. Overview

### Services

| Service | Port | Framework | Purpose |
|---------|------|-----------|---------|
| auth-service | 8001 | FastAPI | Authentication, authorization, user/org management |
| rule-engine-service | 8002 | FastAPI | Rule creation, evaluation, alerts |
| waste-analysis-service | 8003 | FastAPI | Wastage analysis and reporting |
| energy-service | 8004 | FastAPI | Energy monitoring and calculations |
| data-export-service | 8005 | FastAPI | Telemetry data export to S3 |

### Architecture Summary

- **Authentication**: JWT-based with access/refresh tokens
- **Multi-tenancy**: Tenant ID extracted from auth token (X-Tenant-Id header)
- **Data Flow**: Device → Telemetry → Rule Engine → Alerts → Notifications
- **Background Jobs**: Waste analysis runs as background task with timeout handling

---

## 2. Endpoints

---

### 2.1 Auth Service (port 8001)

Base path: `/api/v1/auth`

#### POST /api/v1/auth/login

**Description:** Authenticate user and obtain access/refresh tokens.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepassword"
}
```

**Response (200):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Status Codes:** 200, 401, 422

**Data Flow:** API → AuthService.login() → UserRepository → DB

---

#### POST /api/v1/auth/refresh

**Description:** Refresh access token using refresh token.

**Request:**
```json
{
  "refresh_token": "eyJ..."
}
```
Or via cookie `refresh_token`.

**Response (200):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Status Codes:** 200, 401, 422

**Data Flow:** API → AuthService.refresh() → TokenService → DB

---

#### POST /api/v1/auth/logout

**Description:** Invalidate refresh token and clear session.

**Request:**
```json
{
  "refresh_token": "eyJ..."
}
```
Or via cookie.

**Response (200):**
```json
{
  "message": "Logged out successfully"
}
```

**Status Codes:** 200

**Data Flow:** API → AuthService.logout() → TokenService → DB (revoke tokens)

---

#### GET /api/v1/auth/me

**Description:** Get current authenticated user details, org, and entitlements.

**Auth Required:** Yes (any authenticated role)

**Response (200):**
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "full_name": "John Doe",
    "role": "org_admin",
    "org_id": "uuid",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00Z",
    "last_login_at": "2024-01-15T00:00:00Z"
  },
  "org": { "id": "uuid", "name": "Org Name", "slug": "org-slug", "is_active": true },
  "plant_ids": ["plant-uuid-1"],
  "entitlements": {
    "premium_feature_grants": ["feature1"],
    "role_feature_matrix": { "org_admin": ["feature1"] },
    "baseline_features_by_role": { "org_admin": ["feature2"] },
    "effective_features_by_role": { "org_admin": ["feature1", "feature2"] },
    "available_features": ["feature1", "feature2"],
    "entitlements_version": 1
  }
}
```

**Status Codes:** 200, 401, 403, 404

**Data Flow:** API → AuthService.get_user_by_token_claims() → UserRepository + OrgRepository → DB

---

#### POST /api/v1/auth/invitations/accept

**Description:** Accept invitation and set password.

**Request:**
```json
{
  "token": "invitation-token-string",
  "password": "newpassword",
  "confirm_password": "newpassword"
}
```

**Response (200):**
```json
{
  "message": "Password set successfully. Please sign in."
}
```

**Status Codes:** 200, 400, 422

**Data Flow:** API → AuthService.accept_invitation() → UserRepository (activate user) → DB

---

#### POST /api/v1/auth/password/forgot

**Description:** Request password reset email.

**Request:**
```json
{
  "email": "user@example.com"
}
```

**Response (200):**
```json
{
  "message": "If that email is registered, a password reset link has been sent."
}
```

**Status Codes:** 200

**Data Flow:** API → AuthService.request_password_reset() → ActionTokenService → MailerService → Email

---

#### POST /api/v1/auth/password/reset

**Description:** Reset password using token.

**Request:**
```json
{
  "token": "reset-token-string",
  "password": "newpassword",
  "confirm_password": "newpassword"
}
```

**Response (200):**
```json
{
  "message": "Password reset successfully. Please sign in."
}
```

**Status Codes:** 200, 400, 422

**Data Flow:** API → AuthService.reset_password() → UserRepository → DB

---

#### GET /api/v1/auth/action-token/{token}/status

**Description:** Check status of action token (invite/reset).

**Path Parameters:** `token` - Action token string

**Response (200):**
```json
{
  "status": "valid",
  "action_type": "invite_set_password",
  "email": "user@example.com",
  "full_name": "John Doe"
}
```

**Status Codes:** 200

**Data Flow:** API → AuthService.get_action_token_status() → ActionTokenRepository → DB

---

### 2.2 Admin Endpoints (auth-service)

Base path: `/api/admin` (Super Admin only)

#### POST /api/admin/orgs

**Description:** Create new organization.

**Auth Required:** Super Admin

**Request:**
```json
{
  "name": "Organization Name",
  "slug": "org-slug"
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "name": "Organization Name",
  "slug": "org-slug",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Status Codes:** 201, 409

**Data Flow:** API → OrgRepository.create() → DB

---

#### GET /api/admin/orgs

**Description:** List all organizations.

**Auth Required:** Super Admin

**Response (200):**
```json
[
  { "id": "uuid", "name": "Org 1", "slug": "org1", "is_active": true },
  { "id": "uuid", "name": "Org 2", "slug": "org2", "is_active": false }
]
```

**Status Codes:** 200

**Data Flow:** API → OrgRepository.list_all() → DB

---

#### POST /api/admin/users

**Description:** Create org_admin user.

**Auth Required:** Super Admin

**Request:**
```json
{
  "email": "admin@example.com",
  "full_name": "Admin User",
  "role": "org_admin",
  "org_id": "org-uuid",
  "password": "securepassword"
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "email": "admin@example.com",
  "full_name": "Admin User",
  "role": "org_admin",
  "org_id": "org-uuid",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z",
  "last_login_at": null
}
```

**Status Codes:** 201, 404, 409, 422

**Data Flow:** API → UserRepository.create() → DB

---

#### GET /api/admin/users

**Description:** List users (all or by org).

**Auth Required:** Super Admin

**Query Parameters:**
- `org_id` (optional): Filter by organization

**Response (200):**
```json
[
  { "id": "uuid", "email": "user@example.com", "role": "org_admin", ... }
]
```

**Status Codes:** 200

**Data Flow:** API → UserRepository.list_by_org() / User.select() → DB

---

### 2.3 Organization Endpoints (auth-service)

Base path: `/api/v1/orgs`

#### POST /api/v1/orgs/{org_id}/plants

**Description:** Create plant under organization.

**Auth Required:** Org Admin or above

**Request:**
```json
{
  "name": "Plant Name",
  "location": "City, Country",
  "timezone": "Asia/Kolkata"
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "org_id": "org-uuid",
  "name": "Plant Name",
  "location": "City, Country",
  "timezone": "Asia/Kolkata",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Status Codes:** 201, 404

**Data Flow:** API → PlantRepository.create() → DB

---

#### GET /api/v1/orgs/{org_id}/plants

**Description:** List plants in organization.

**Auth Required:** Any authenticated

**Response (200):**
```json
[
  { "id": "uuid", "name": "Plant 1", "location": "City", ... }
]
```

**Status Codes:** 200

**Data Flow:** API → PlantRepository.list_by_org() → DB

---

#### POST /api/v1/orgs/{org_id}/users

**Description:** Invite user to organization.

**Auth Required:** Org Admin, Plant Manager

**Request:**
```json
{
  "email": "user@example.com",
  "full_name": "New User",
  "role": "operator",
  "org_id": "org-uuid",
  "plant_ids": ["plant-uuid-1"]
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "New User",
  "role": "operator",
  "org_id": "org-uuid",
  "is_active": false,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Status Codes:** 201, 403, 404, 409

**Data Flow:** API → AuthService.send_invitation() → UserRepository → DB → MailerService (send invite email)

---

#### GET /api/v1/orgs/{org_id}/users

**Description:** List users in organization.

**Auth Required:** Org Admin or above

**Response (200):**
```json
[
  { "id": "uuid", "email": "user@example.com", "role": "operator", ... }
]
```

**Status Codes:** 200

**Data Flow:** API → UserRepository.list_by_org() → DB

---

#### GET /api/v1/orgs/{org_id}/entitlements

**Description:** Get feature entitlements for organization.

**Auth Required:** Org Admin or above

**Response (200):**
```json
{
  "premium_feature_grants": ["feature1"],
  "role_feature_matrix": { "org_admin": ["feature1"] },
  "baseline_features_by_role": { "operator": ["feature2"] },
  "effective_features_by_role": { "org_admin": ["feature1", "feature2"] },
  "available_features": ["feature1", "feature2"],
  "entitlements_version": 1
}
```

**Status Codes:** 200, 404

**Data Flow:** API → OrgRepository.get_by_id() → build_feature_entitlement_state() → Response

---

#### PUT /api/v1/orgs/{org_id}/entitlements

**Description:** Update feature entitlements.

**Auth Required:** Org Admin or Super Admin

**Request:**
```json
{
  "premium_feature_grants": ["feature1", "feature2"],
  "role_feature_matrix": { "operator": ["feature1"] }
}
```
(Only one of premium_feature_grants or role_feature_matrix allowed based on role)

**Response (200):**
```json
{
  "premium_feature_grants": ["feature1", "feature2"],
  "role_feature_matrix": { "operator": ["feature1"] },
  "baseline_features_by_role": { ... },
  "effective_features_by_role": { ... },
  "available_features": [...],
  "entitlements_version": 2
}
```

**Status Codes:** 200, 403, 404, 422

**Data Flow:** API → OrgRepository.update_entitlements() → DB

---

#### PUT /api/v1/orgs/{org_id}/users/{user_id}
#### PATCH /api/v1/orgs/{org_id}/users/{user_id}

**Description:** Update user details.

**Auth Required:** Org Admin or above

**Request:**
```json
{
  "full_name": "Updated Name",
  "role": "operator",
  "is_active": true,
  "plant_ids": ["plant-uuid-1", "plant-uuid-2"]
}
```

**Response (200):**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "full_name": "Updated Name",
  "role": "operator",
  "org_id": "org-uuid",
  "is_active": true
}
```

**Status Codes:** 200, 403, 404

**Data Flow:** API → UserRepository.update() → UserRepository.set_plant_access() → TokenService.revoke_all_user_tokens() → DB

---

#### GET /api/v1/orgs/{org_id}/users/{user_id}/plant-access

**Description:** Get user's plant access.

**Auth Required:** Org Admin or above

**Response (200):**
```json
{
  "plant_ids": ["plant-uuid-1"]
}
```

**Status Codes:** 200, 404

**Data Flow:** API → UserRepository.get_plant_ids() → DB

---

#### POST /api/v1/orgs/{org_id}/users/{user_id}/resend-invite

**Description:** Resend invitation email.

**Auth Required:** Org Admin, Plant Manager

**Response (200):**
```json
{
  "message": "Invitation email resent."
}
```

**Status Codes:** 200, 403, 409

**Data Flow:** API → AuthService.resend_invitation() → MailerService → Email

---

#### PATCH /api/v1/orgs/{org_id}/users/{user_id}/deactivate

**Description:** Deactivate user.

**Auth Required:** Org Admin or above

**Response (200):**
```json
{
  "message": "User deactivated"
}
```

**Status Codes:** 200, 403, 404

**Data Flow:** API → UserRepository.update() + TokenService.revoke_all_user_tokens() → DB

---

### 2.4 Rule Engine Service (port 8002)

Base path: `/api/v1/rules`

#### GET /api/v1/rules/{rule_id}

**Description:** Get rule by ID.

**Auth Required:** Yes (feature: rules)

**Path Parameters:** `rule_id` (UUID)

**Response (200):**
```json
{
  "success": true,
  "data": {
    "rule_id": "uuid",
    "tenant_id": "tenant-uuid",
    "rule_name": "Temperature Alert",
    "description": "Alert when temperature exceeds 80",
    "rule_type": "threshold",
    "scope": "selected_devices",
    "device_ids": ["device-1", "device-2"],
    "property": "temperature",
    "condition": ">",
    "threshold": 80,
    "notification_channels": ["email"],
    "status": "active",
    "cooldown_minutes": 30,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
  }
}
```

**Status Codes:** 200, 404, 500

**Data Flow:** API → RuleService.get_rule() → DB

---

#### GET /api/v1/rules

**Description:** List all rules with filtering and pagination.

**Auth Required:** Yes (feature: rules)

**Query Parameters:**
- `status` (optional): Filter by status (active, paused, archived)
- `device_id` (optional): Filter by device
- `page`: Page number (default 1)
- `page_size`: Items per page (default 20, max 100)

**Response (200):**
```json
{
  "success": true,
  "data": [...],
  "total": 50,
  "page": 1,
  "page_size": 20,
  "total_pages": 3
}
```

**Status Codes:** 200, 500

**Data Flow:** API → RuleService.list_rules() → DB

---

#### POST /api/v1/rules

**Description:** Create new rule.

**Auth Required:** Yes (feature: rules)

**Request:**
```json
{
  "rule_name": "Temperature Alert",
  "description": "Alert when temperature exceeds 80",
  "rule_type": "threshold",
  "scope": "selected_devices",
  "device_ids": ["device-1"],
  "property": "temperature",
  "condition": ">",
  "threshold": 80,
  "notification_channels": ["email"],
  "cooldown_minutes": 30
}
```

**Response (201):**
```json
{
  "success": true,
  "data": { "rule_id": "uuid", "status": "active", ... }
}
```

**Status Codes:** 201, 400, 500

**Data Flow:** API → RuleService.create_rule() → DB → NotificationAdapter.send_alert() (if email channel)

**Error Handling:**
- Validation error: 400 with VALIDATION_ERROR code
- DB error: 500 with INTERNAL_ERROR code

---

#### PUT /api/v1/rules/{rule_id}

**Description:** Update existing rule.

**Auth Required:** Yes (feature: rules)

**Request:** Partial rule object

**Response (200):**
```json
{
  "success": true,
  "data": { ... }
}
```

**Status Codes:** 200, 400, 404, 500

**Data Flow:** API → RuleService.update_rule() → DB

---

#### PATCH /api/v1/rules/{rule_id}/status

**Description:** Update rule status (active/paused/archived).

**Auth Required:** Yes (feature: rules)

**Request:**
```json
{
  "status": "paused"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Rule paused successfully",
  "rule_id": "uuid",
  "status": "paused"
}
```

**Status Codes:** 200, 404, 500

**Data Flow:** API → RuleService.update_rule_status() → DB

---

#### DELETE /api/v1/rules/{rule_id}

**Description:** Delete rule.

**Auth Required:** Yes (feature: rules)

**Query Parameters:**
- `soft`: Soft delete (default true)

**Response (200):**
```json
{
  "success": true,
  "message": "Rule deleted successfully",
  "rule_id": "uuid"
}
```

**Status Codes:** 200, 404, 500

**Data Flow:** API → RuleService.delete_rule() → DB (marks deleted_at or removes)

---

#### POST /api/v1/rules/evaluate

**Description:** Evaluate telemetry payload against active rules.

**Auth Required:** Yes (feature: rules)

**Request:**
```json
{
  "device_id": "device-1",
  "timestamp": "2024-01-01T12:00:00Z",
  "temperature": 85,
  "voltage": 220,
  "current": 10,
  "power": 2200
}
```

**Response (200):**
```json
{
  "rules_evaluated": 5,
  "rules_triggered": 2,
  "results": [
    {
      "rule_id": "uuid",
      "rule_name": "Temperature Alert",
      "triggered": true,
      "actual_value": 85,
      "threshold": 80,
      "condition": ">",
      "message": "Temperature 85 exceeds threshold 80"
    }
  ]
}
```

**Status Codes:** 200, 400, 500

**Data Flow:** API → RuleEvaluator.evaluate_telemetry() → DB (fetch active rules) → Evaluate conditions → Create Alert

**Error Handling:**
- ValueError: 400 with EVALUATION_ERROR code
- Exception: 500 with INTERNAL_ERROR code

---

### 2.5 Alerts Endpoints (rule-engine-service)

Base path: `/api/v1/alerts`

#### GET /api/v1/alerts

**Description:** List alerts with filtering and pagination.

**Auth Required:** Yes (feature: rules)

**Query Parameters:**
- `device_id` (optional): Filter by device
- `rule_id` (optional): Filter by rule
- `status` (optional): Filter by status
- `page`: Page number
- `page_size`: Items per page

**Response (200):**
```json
{
  "success": true,
  "data": [
    {
      "alert_id": "uuid",
      "rule_id": "uuid",
      "device_id": "device-1",
      "severity": "critical",
      "message": "Temperature exceeded threshold",
      "actual_value": 85,
      "threshold_value": 80,
      "status": "open",
      "created_at": "2024-01-01T12:00:00Z"
    }
  ],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "total_pages": 5
}
```

**Status Codes:** 200, 500

**Data Flow:** API → AlertRepository.list_alerts() → DB

---

#### PATCH /api/v1/alerts/{alert_id}/acknowledge

**Description:** Acknowledge alert.

**Auth Required:** Yes (feature: rules)

**Request:**
```json
{
  "acknowledged_by": "user@example.com"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": { "alert_id": "uuid", "status": "acknowledged", "acknowledged_by": "user@example.com" }
}
```

**Status Codes:** 200, 404, 500

**Data Flow:** API → AlertRepository.acknowledge_alert() → DB → ActivityEventService.create_event() (alert_acknowledged)

---

#### PATCH /api/v1/alerts/{alert_id}/resolve

**Description:** Mark alert as resolved.

**Auth Required:** Yes (feature: rules)

**Response (200):**
```json
{
  "success": true,
  "data": { "alert_id": "uuid", "status": "resolved" }
}
```

**Status Codes:** 200, 404, 500

**Data Flow:** API → AlertRepository.resolve_alert() → DB → ActivityEventService.create_event() (alert_resolved)

---

#### GET /api/v1/alerts/events

**Description:** List activity events.

**Auth Required:** Yes (feature: rules)

**Query Parameters:**
- `device_id` (optional)
- `event_type` (optional)
- `page`, `page_size`

**Response (200):**
```json
{
  "success": true,
  "data": [...],
  "total": 50,
  "page": 1,
  "page_size": 20,
  "total_pages": 3
}
```

**Status Codes:** 200, 500

**Data Flow:** API → ActivityEventRepository.list_events() → DB

---

#### GET /api/v1/alerts/events/unread-count

**Description:** Get unread activity events count.

**Auth Required:** Yes (feature: rules)

**Response (200):**
```json
{
  "success": true,
  "data": { "count": 10 }
}
```

**Status Codes:** 200

**Data Flow:** API → ActivityEventRepository.unread_count() → DB

---

#### PATCH /api/v1/alerts/events/mark-all-read

**Description:** Mark all events as read.

**Auth Required:** Yes (feature: rules)

**Response (200):**
```json
{
  "success": true,
  "data": { "updated": 15 }
}
```

**Status Codes:** 200

**Data Flow:** API → ActivityEventRepository.mark_all_read() → DB

---

#### DELETE /api/v1/alerts/events

**Description:** Clear event history.

**Auth Required:** Yes (feature: rules)

**Response (200):**
```json
{
  "success": true,
  "data": { "deleted": 20 }
}
```

**Status Codes:** 200

**Data Flow:** API → ActivityEventRepository.clear_history() → DB

---

#### GET /api/v1/alerts/events/summary

**Description:** Get activity summary for dashboard.

**Auth Required:** Yes (feature: rules)

**Response (200):**
```json
{
  "success": true,
  "data": {
    "active_alerts": 5,
    "alerts_triggered": 20,
    "alerts_cleared": 15,
    "rules_created": 10,
    "rules_updated": 5,
    "rules_deleted": 2
  }
}
```

**Status Codes:** 200

**Data Flow:** API → ActivityEventRepository.count_by_event_types() + AlertRepository.count_by_status() → DB

---

### 2.6 Waste Analysis Service (port 8003)

Base path: `/api/v1/waste`

#### POST /api/v1/waste/analysis/run

**Description:** Start waste analysis job.

**Auth Required:** Yes (feature: waste_analysis)

**Request:**
```json
{
  "job_name": "January Analysis",
  "scope": "selected",
  "device_ids": ["device-1", "device-2"],
  "start_date": "2024-01-01",
  "end_date": "2024-01-31",
  "granularity": "daily"
}
```

**Response (202):**
```json
{
  "job_id": "uuid",
  "status": "pending",
  "estimated_completion_seconds": 30
}
```

**Status Codes:** 202, 400

**Data Flow:** API → WasteRepository.create_job() → DB → Background Task (run_waste_analysis)

**Error Handling:**
- Validation error: 400 with VALIDATION_ERROR code
- Duplicate job: Returns existing job_id

---

#### GET /api/v1/waste/analysis/{job_id}/status

**Description:** Get job status.

**Auth Required:** Yes (feature: waste_analysis)

**Path Parameters:** `job_id`

**Response (200):**
```json
{
  "job_id": "uuid",
  "status": "completed",
  "progress_pct": 100,
  "stage": "Finalizing",
  "error_code": null,
  "error_message": null
}
```

**Status Codes:** 200, 404

**Data Flow:** API → WasteRepository.get_job() → DB

---

#### GET /api/v1/waste/analysis/{job_id}/result

**Description:** Get job result.

**Auth Required:** Yes (feature: waste_analysis)

**Response (200):**
```json
{
  "summary": { ... },
  "details": [ ... ]
}
```

**Status Codes:** 200, 400, 404

**Data Flow:** API → WasteRepository.get_job() → DB (result_json)

---

#### GET /api/v1/waste/analysis/{job_id}/download

**Description:** Get download URL for PDF report.

**Auth Required:** Yes (feature: waste_analysis)

**Response (200):**
```json
{
  "job_id": "uuid",
  "download_url": "https://minio.../report.pdf?signature=...",
  "expires_in_seconds": 900
}
```

**Status Codes:** 200, 404

**Data Flow:** API → WasteRepository.get_job() → MinioClient.get_presigned_url()

**Dead Queue/Error Flow:**
- If job fails: status = "failed", error_code set
- If S3 key missing: 404
- Timeout: JOB_TIMEOUT error after WASTE_JOB_TIMEOUT_SECONDS (default configurable)

---

#### GET /api/v1/waste/analysis/history

**Description:** Get job history.

**Auth Required:** Yes (feature: waste_analysis)

**Query Parameters:**
- `limit`: Max items (default 20, max 100)
- `offset`: Offset for pagination

**Response (200):**
```json
{
  "items": [
    {
      "job_id": "uuid",
      "job_name": "January Analysis",
      "status": "completed",
      "error_code": null,
      "error_message": null,
      "created_at": "2024-01-01T00:00:00Z",
      "completed_at": "2024-01-01T00:05:00Z",
      "progress_pct": 100
    }
  ]
}
```

**Status Codes:** 200

**Data Flow:** API → WasteRepository.list_jobs() → DB

---

### 2.7 Energy Service (port 8004)

Base path: `/api/v1/energy`

#### POST /api/v1/energy/live-update

**Description:** Apply live telemetry update and broadcast.

**Auth Required:** Yes

**Request:**
```json
{
  "telemetry": {
    "device_id": "device-1",
    "voltage": 220,
    "current": 10,
    "power": 2200,
    "temperature": 45
  },
  "dynamic_fields": {
    "custom_metric": 100
  },
  "tenant_id": "tenant-uuid"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "device_id": "device-1",
    "version": 5,
    "applied_at": "2024-01-01T12:00:00Z"
  }
}
```

**Status Codes:** 200, 400

**Data Flow:** API → EnergyEngine.apply_live_update() → DB → EnergyBroadcaster.publish() → Redis

---

#### POST /api/v1/energy/device-lifecycle/{device_id}

**Description:** Update device lifecycle status.

**Auth Required:** Yes

**Path Parameters:** `device_id`

**Request:**
```json
{
  "status": "running",
  "at": "2024-01-01T12:00:00Z"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "device_id": "device-1",
    "version": 6,
    "freshness_ts": "2024-01-01T12:00:00Z"
  }
}
```

**Status Codes:** 200

**Data Flow:** API → EnergyEngine.apply_device_lifecycle() → DB → EnergyBroadcaster.publish() → Redis

---

#### GET /api/v1/energy/summary

**Description:** Get energy summary for tenant.

**Auth Required:** Yes

**Response (200):**
```json
{
  "success": true,
  "total_energy_kwh": 15000,
  "active_devices": 10,
  "alerts_count": 3
}
```

**Status Codes:** 200

**Data Flow:** API → EnergyEngine.get_summary() → DB

---

#### GET /api/v1/energy/today-loss-breakdown

**Description:** Get today's energy loss breakdown.

**Auth Required:** Yes

**Response (200):**
```json
{
  "success": true,
  "loss_breakdown": {
    "idle": 100,
    "standby": 50,
    "excess": 25
  }
}
```

**Status Codes:** 200

**Data Flow:** API → EnergyEngine.get_today_loss_breakdown() → DB

---

#### GET /api/v1/energy/calendar/monthly

**Description:** Get monthly calendar data.

**Auth Required:** Yes (feature: calendar)

**Query Parameters:**
- `year`: Year (2000-2100)
- `month`: Month (1-12)

**Response (200):**
```json
{
  "success": true,
  "calendar": {
    "2024-01-01": { "energy_kwh": 100, "status": "normal" },
    "2024-01-02": { "energy_kwh": 120, "status": "normal" }
  }
}
```

**Status Codes:** 200

**Data Flow:** API → EnergyEngine.get_monthly_calendar() → DB

---

#### GET /api/v1/energy/device/{device_id}/range

**Description:** Get device energy data for date range.

**Auth Required:** Yes

**Query Parameters:**
- `start_date`: Start date (YYYY-MM-DD)
- `end_date`: End date (YYYY-MM-DD)

**Response (200):**
```json
{
  "success": true,
  "device_id": "device-1",
  "start_date": "2024-01-01",
  "end_date": "2024-01-31",
  "totals": { "energy_kwh": 5000, "cost_inr": 45000 },
  "days": [
    { "date": "2024-01-01", "energy_kwh": 150, "cost_inr": 1350 }
  ],
  "version": 10,
  "freshness_ts": "2024-01-31T23:59:59Z"
}
```

**Status Codes:** 200

**Data Flow:** API → EnergyEngine.get_device_range() → DB

---

### 2.8 Data Export Service (port 8005)

Base path: `/api/v1/exports`

#### POST /api/v1/exports/run

**Description:** Trigger on-demand data export.

**Auth Required:** Yes

**Request:**
```json
{
  "device_id": "device-1",
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-31T23:59:59Z",
  "request_id": "optional-request-id"
}
```

**Response (200):**
```json
{
  "status": "accepted",
  "device_id": "device-1",
  "request_id": "optional-request-id",
  "mode": "forced_range",
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-31T23:59:59Z"
}
```

**Status Codes:** 200, 422, 503

**Data Flow:** API → ExportWorker.force_export() → DataSource → S3Writer → S3

**Error Handling:**
- Validation error: 422 with VALIDATION_ERROR code
- Worker not running: 503

---

#### GET /api/v1/exports/status/{device_id}

**Description:** Get export status for device.

**Auth Required:** Yes

**Response (200):**
```json
{
  "device_id": "device-1",
  "last_export_ts": "2024-01-31T23:59:59Z",
  "status": "completed"
}
```

**Status Codes:** 200, 503

**Data Flow:** API → Exporter.get_export_status()

---

### 2.9 Health/Readiness Endpoints

All services expose health check endpoints:

| Service | Endpoint | Response |
|---------|----------|----------|
| auth-service | GET /health | `{"status": "ok", "service": "auth-service"}` |
| auth-service | GET /ready | `{"status": "ready"}` or 503 |
| rule-engine-service | GET /health | `{"status": "healthy", "service": "rule-engine-service", "version": "1.0.0"}` |
| rule-engine-service | GET /ready | `{"status": "ready"}` or 503 |
| waste-analysis-service | GET /health | `{"status": "healthy"}` |
| waste-analysis-service | GET /ready | `{"status": "ready"}` |
| energy-service | GET /health | `{"status": "healthy", "service": "energy-service"}` |
| energy-service | GET /api/v1/energy/health | `{"status": "healthy", "service": "energy-service"}` |
| data-export-service | GET /health | `{"status": "healthy", "version": "1.0.0", "timestamp": "..."}` |
| data-export-service | GET /ready | `{"ready": true, "checks": {...}}` or 503 |

---

## 3. Data Flow Summary

### Authentication Flow
```
User → Login API → AuthService → UserRepository → DB
                           ↓
                    TokenService (JWT)
                           ↓
                    Response (tokens)
```

### Rule Evaluation Flow
```
Telemetry → /rules/evaluate → RuleEvaluator → DB (fetch rules)
                                           ↓
                                    Evaluate conditions
                                           ↓
                                    AlertRepository (create alert)
                                           ↓
                                    NotificationAdapter (send notification)
```

### Waste Analysis Flow
```
Request → /analysis/run → WasteRepository (create job)
                                   ↓
                          Background Task
                                   ↓
                          WasteEngine (calculate)
                                   ↓
                          S3Writer (save PDF)
                                   ↓
                          Job status: completed/failed
```

### Energy Update Flow
```
Live Update API → EnergyEngine → DB
                           ↓
                   EnergyBroadcaster.publish() → Redis
                                              ↓
                                      WebSocket Clients
```

---

## 4. Error Handling & Dead Queues

### Common Error Codes

| Code | Description | HTTP Status |
|------|-------------|-------------|
| VALIDATION_ERROR | Request validation failed | 422 |
| AUTHENTICATION_ERROR | Invalid/missing credentials | 401 |
| FORBIDDEN | Insufficient permissions | 403 |
| ORG_NOT_FOUND | Organization not found | 404 |
| USER_NOT_FOUND | User not found | 404 |
| RULE_NOT_FOUND | Rule not found | 404 |
| ALERT_NOT_FOUND | Alert not found | 404 |
| INTERNAL_ERROR | Unexpected server error | 500 |
| SERVICE_UNAVAILABLE | Service not ready | 503 |

### Waste Analysis Job Failure Handling

- **Timeout**: Job marked as failed with `JOB_TIMEOUT` error code after `WASTE_JOB_TIMEOUT_SECONDS`
- **Service Restart**: Stale jobs (pending/processing > 10 min) marked failed on startup
- **Retry**: Clients should retry by calling `/analysis/run` again

### Rule Evaluation Error Handling

- **ValueError**: Returns 400 with `EVALUATION_ERROR` code
- **Unexpected Exception**: Returns 500 with `INTERNAL_ERROR` code, logs full traceback

---

## 5. Authentication

All endpoints (except health/readiness) require JWT authentication.

### Headers

| Header | Description |
|--------|-------------|
| `Authorization` | `Bearer <access_token>` |
| `X-Target-Tenant-Id` | Tenant ID (for Super Admin) |

### Token Types

- **Access Token**: Short-lived (15 min default), used in Authorization header
- **Refresh Token**: Long-lived (7 days default), used to obtain new access tokens

---

## 6. Feature Entitlements

Access to certain endpoints is controlled by feature flags:

| Feature | Required For |
|---------|--------------|
| rules | Rule Engine endpoints |
| waste_analysis | Waste Analysis endpoints |
| calendar | Energy calendar endpoint |

Entitlements are computed per-organization and returned in `/api/v1/auth/me`.

---

*This documentation is auto-generated from the codebase. To regenerate, run the API discovery script.*
