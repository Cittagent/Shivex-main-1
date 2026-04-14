# FactoryOPS Auth Guide

This file is the quick reference for how authentication and authorization work in FactoryOPS after the auth rollout.

## What Was Added

- Central auth service at `http://localhost:8090`
- JWT login, refresh, logout, and `/me`
- Super-admin, org-admin, plant-manager, operator, and viewer roles
- Plant-scoped access using `user_plant_access`
- Shared JWT middleware for the backend services

## Role Model

### `super_admin`

- Can manage all organisations
- Can create `org_admin` users
- Can see all plants and all devices
- Not tied to a single organisation

### `org_admin`

- Belongs to one organisation
- Can create and manage plants for that organisation
- Can create `plant_manager`, `operator`, and `viewer` users for that organisation
- Can see everything inside their organisation

### `plant_manager`

- Belongs to one organisation
- Can be assigned one or more plants
- Can access only the plants in `user_plant_access`

### `operator`

- Belongs to one organisation
- Can be assigned one or more plants
- Can access only the plants in `user_plant_access`

### `viewer`

- Belongs to one organisation
- Can be assigned one or more plants
- Read-only access to assigned plants

## How To Create A Super Admin

Super admins are not created through the API. They are bootstrapped once using the seed script:

```bash
python tools/seed_superadmin.py
```

Interactive example:

```text
Email: admin@factoryops.local
Full name: Super Admin
Password: ********
Confirm password: ********
```

Non-interactive example:

```bash
SEED_EMAIL=admin@factoryops.local \
SEED_PASSWORD=Secret1234 \
SEED_FULLNAME="Super Admin" \
python tools/seed_superadmin.py
```

Important:

- This is the only supported way to create a `super_admin`
- The API does not expose a `super_admin` creation endpoint

## How A Super Admin Creates Admins

Use the auth service admin endpoints with a valid super-admin access token.

### 1. Create an organisation

```bash
curl -X POST http://localhost:8090/api/admin/orgs \
  -H "Authorization: Bearer <SUPER_ADMIN_ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Factory","slug":"acme-factory"}'
```

This creates the organisation record that all later users and plants belong to.

### 2. Create an org admin

```bash
curl -X POST http://localhost:8090/api/admin/users \
  -H "Authorization: Bearer <SUPER_ADMIN_ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "email":"admin@acme.com",
    "password":"Admin1234!",
    "full_name":"Acme Admin",
    "role":"org_admin",
    "org_id":"<ORG_ID>",
    "plant_ids":[]
  }'
```

Notes:

- This endpoint only allows `org_admin`
- If you try `plant_manager`, `operator`, or `viewer` here, it returns `422`

## How An Admin Creates Plant Users

Use the org-scoped endpoint:

```bash
curl -X POST http://localhost:8090/api/v1/orgs/<ORG_ID>/users \
  -H "Authorization: Bearer <ORG_ADMIN_OR_SUPER_ADMIN_ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "email":"operator-a@acme.com",
    "password":"Operator1234!",
    "full_name":"Operator A",
    "role":"operator",
    "org_id":"<ORG_ID>",
    "plant_ids":["<PLANT_A_ID>"]
  }'
```

### What this does

- Creates the user inside the organisation
- Stores the plant mapping in `user_plant_access`
- The user can only access `plant_ids` that were assigned

### Scope example

If you create:

- `operator` for `Plant A`
- with `plant_ids=["Plant A"]`

Then that user should:

- access `Plant A`
- not access `Plant B`
- not access `Plant C`

This plant-level restriction is part of the auth design and is already enforced in the backend services that use the shared middleware and plant checks.

## How To Log In

### Web

- Open `http://localhost:3000/login`
- Use the email/password created by the admin or seed script

### API

```bash
curl -X POST http://localhost:8090/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@factoryops.local","password":"Admin1234!"}'
```

Login returns:

- `access_token`
- `refresh_token`
- `token_type`
- `expires_in`

## How Device Onboarding Works Now

Device onboarding is still done through the device service, but now it should be done with auth in mind.

### Recommended flow

1. Log in as `super_admin` or `org_admin`
2. Create or choose the organisation
3. Create or choose the plant
4. Create the device with both tenant and plant context

Example:

```bash
curl -X POST http://localhost:8000/api/v1/devices \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id":"COMPRESSOR-001",
    "tenant_id":"<ORG_ID>",
    "plant_id":"<PLANT_ID>",
    "device_name":"Compressor 001",
    "device_type":"compressor",
    "location":"Plant A",
    "data_source_type":"metered",
    "phase_type":"single"
  }'
```

### Important note

- `viewer` is blocked from creating devices
- `super_admin` and `org_admin` are the intended roles for onboarding devices
- `plant_manager` and `operator` are meant for plant-scoped operational access, not org setup

## How Plant Access Is Enforced

The auth system stores plant access in `user_plant_access` and issues those plant IDs into the JWT.

Backend services then enforce access in two ways:

- by reading the JWT plant list
- by checking the requested plant or device plant against that list

That means:

- `super_admin` can see everything
- `org_admin` can see everything in their organisation
- `plant_manager`, `operator`, and `viewer` can only see assigned plants

## How To Get The Current User

After login, call:

```bash
curl http://localhost:8090/api/v1/auth/me \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

This returns:

- user profile
- organisation
- assigned plant IDs

## Token Notes

- Access token is the short-lived JWT
- Refresh token is stored in an HTTP-only cookie in the web app
- Mobile stores the refresh token in SecureStore because it cannot use HTTP-only cookies

## Production Cutover Summary

When you are ready to require auth everywhere:

1. Keep auth enforcement enabled for the backend services
2. Make sure all internal service calls send `X-Internal-Service`
3. Confirm web login/logout works
4. Confirm mobile login/logout works
5. Run the auth E2E suite

For the exact rollout steps, see `docs/auth_cutover_runbook.md`.
