/* eslint-disable @typescript-eslint/no-require-imports */

const { expect, test } = require("@playwright/test");

function base64Json(value) {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64");
}

async function fulfillJson(route, data, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(data),
  });
}

test("device onboarding generates and displays the device ID after create", async ({ page }) => {
  const me = {
    user: {
      id: "user-1",
      email: "admin@example.com",
      full_name: "Admin User",
      role: "org_admin",
      tenant_id: "SH00000001",
      is_active: true,
      created_at: new Date().toISOString(),
      last_login_at: null,
    },
    org: {
      id: "SH00000001",
      name: "Factory Ops",
      slug: "factory-ops",
      is_active: true,
      created_at: new Date().toISOString(),
    },
    plant_ids: [],
    entitlements: {
      premium_feature_grants: [],
      role_feature_matrix: {
        org_admin: ["machines"],
        plant_manager: [],
        operator: [],
        viewer: [],
        super_admin: ["machines"],
      },
      baseline_features_by_role: {
        org_admin: ["machines"],
        plant_manager: [],
        operator: [],
        viewer: [],
        super_admin: ["machines"],
      },
      effective_features_by_role: {
        org_admin: ["machines"],
        plant_manager: [],
        operator: [],
        viewer: [],
        super_admin: ["machines"],
      },
      available_features: ["machines"],
      entitlements_version: 1,
    },
  };

  const createdDeviceId = "AD00000001";
  let createRequestBody = null;

  await page.addInitScript((snapshot) => {
    window.sessionStorage.setItem("factoryops_access_token", snapshot.accessToken);
    window.sessionStorage.setItem("factoryops_refresh_token", "refresh-token");
    window.sessionStorage.setItem("factoryops_me", JSON.stringify(snapshot.me));
  }, {
    accessToken: `header.${base64Json({ role: "org_admin", tenant_id: "SH00000001" })}.signature`,
    me,
  });

  await page.route("**/backend/auth/api/v1/auth/me", async (route) => {
    await fulfillJson(route, me);
  });
  await page.route("**/backend/auth/api/v1/auth/refresh", async (route) => {
    await fulfillJson(route, {
      access_token: `header.${base64Json({ role: "org_admin", tenant_id: "SH00000001" })}.signature`,
      refresh_token: "refresh-token",
      token_type: "bearer",
      expires_in: 3600,
    });
  });
  await page.route("**/backend/auth/api/v1/tenants/SH00000001/plants", async (route) => {
    await fulfillJson(route, [{ id: "plant-1", name: "Plant One" }]);
  });
  await page.route("**/backend/device/api/v1/devices", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    createRequestBody = route.request().postDataJSON();
    await fulfillJson(route, {
      success: true,
      data: {
        device_id: createdDeviceId,
        device_name: "Compressor Line A",
        device_type: "compressor",
        device_id_class: "active",
        data_source_type: "metered",
        status: "active",
        runtime_status: "stopped",
        last_seen_timestamp: null,
        location: "Building A",
      },
    }, 201);
  });
  await page.route("**/backend/device/api/v1/devices/dashboard/summary", async (route) => {
    await fulfillJson(route, {
      generated_at: new Date().toISOString(),
      stale: false,
      warnings: [],
      summary: {
        total_devices: 0,
        system_health: 100,
      },
      alerts: {
        active_alerts: 0,
      },
      devices: [],
      cost_data_state: "fresh",
      cost_data_reasons: [],
      cost_generated_at: null,
      energy_widgets: {
        today_loss_kwh: 0,
        today_loss_cost_inr: 0,
        currency: "INR",
      },
    });
  });
  await page.route("**/backend/device/api/v1/devices/dashboard/fleet-snapshot**", async (route) => {
    await fulfillJson(route, {
      generated_at: new Date().toISOString(),
      total: 0,
      page: 1,
      page_size: 60,
      total_pages: 1,
      devices: [],
    });
  });
  await page.route("**/backend/device/api/v1/devices/dashboard/fleet-stream**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body:
        "id: 1\n" +
        "event: heartbeat\n" +
        'data: {"id":"1","event":"heartbeat","generated_at":"2026-04-02T00:00:00.000Z","freshness_ts":"2026-04-02T00:00:00.000Z","stale":false,"warnings":[],"devices":[],"partial":false,"version":0}\n\n',
    });
  });
  await page.route("**/backend/rule-engine/api/v1/alerts/events/unread-count**", async (route) => {
    await fulfillJson(route, { data: { count: 0 } });
  });
  await page.route("**/backend/rule-engine/api/v1/alerts/events**", async (route) => {
    if (route.request().method() === "DELETE") {
      await fulfillJson(route, { data: { deleted: 0 } });
      return;
    }
    await fulfillJson(route, {
      data: [],
      total: 0,
      page: 1,
      page_size: 25,
      total_pages: 1,
    });
  });

  await page.goto("/machines");
  await page.getByRole("button", { name: "+ Add Device" }).click();

  await expect(page.locator("label").filter({ hasText: /^Device ID$/ })).toHaveCount(0);
  await expect(page.locator("label").filter({ hasText: /^Device ID Class \*$/ })).toBeVisible();
  await expect(page.getByText("MQTT topic after provisioning:")).toBeVisible();

  await page.locator('input[placeholder="e.g. Compressor Line A"]').fill("Compressor Line A");
  await page.locator("select").nth(0).selectOption("plant-1");
  await page.locator('input[placeholder="e.g. Compressor, Chiller, Motor"]').fill("compressor");
  await page.locator("select").filter({ has: page.locator('option[value="active"]') }).first().selectOption("active");
  await page.locator('input[placeholder="e.g. Atlas Copco"]').fill("Atlas Copco");
  await page.locator('input[placeholder="e.g. GA37"]').fill("GA37");
  await page.locator('input[placeholder="e.g. Building A, Floor 1"]').fill("Building A");
  await page.getByRole("button", { name: "Add Device", exact: true }).click();

  expect(createRequestBody).toBeTruthy();
  expect(createRequestBody.device_id).toBeUndefined();
  expect(createRequestBody.device_id_class).toBe("active");
  await expect(page.getByText("Generated Device ID", { exact: true })).toBeVisible();
  await expect(page.getByText(createdDeviceId, { exact: true })).toBeVisible();
  await expect(page.getByText(`SH00000001/devices/${createdDeviceId}/telemetry`)).toBeVisible();
});
