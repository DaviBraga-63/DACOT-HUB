const { test, expect, request } = require("@playwright/test");
const crypto = require("crypto");
const fs = require("fs");

const HUB_API = process.env.E2E_HUB_API;
const HUB_UI = process.env.E2E_HUB_UI;
const ORDERS_API = process.env.E2E_ORDERS_API;
const ORDERS_UI = process.env.E2E_ORDERS_UI;
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL;
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD;
const EMPLOYEE_PASSWORD = process.env.E2E_EMPLOYEE_PASSWORD;
const RESULTS_FILE = process.env.E2E_RESULTS_FILE || "e2e-results.json";

for (const [name, value] of Object.entries({
  E2E_HUB_API: HUB_API,
  E2E_HUB_UI: HUB_UI,
  E2E_ORDERS_API: ORDERS_API,
  E2E_ORDERS_UI: ORDERS_UI,
  E2E_ADMIN_EMAIL: ADMIN_EMAIL,
  E2E_ADMIN_PASSWORD: ADMIN_PASSWORD,
  E2E_EMPLOYEE_PASSWORD: EMPLOYEE_PASSWORD,
})) {
  if (!value) throw new Error(`${name} is required for isolated browser E2E tests`);
}

const tag = `e2e-${crypto.randomUUID().slice(0, 8)}`;
const evidence = { scenario: "tenant_user_revocation", pages: {}, backend: {} };

function tabHeaders(binding, tabId = crypto.randomUUID()) {
  return {
    "X-DACOT-Tab-Session": tabId,
    Cookie: `__Host-dacot_browser=${binding}`,
  };
}

async function authenticatedHubApi(email, password) {
  const api = await request.newContext({ baseURL: HUB_API, ignoreHTTPSErrors: true });
  const tabId = crypto.randomUUID();
  const login = await api.post("/api/auth/login", {
    headers: { "X-DACOT-Tab-Session": tabId },
    data: { email, password },
  });
  expect(login.status(), "Hub login used to seed isolated E2E data").toBe(200);
  const cookie = login.headers()["set-cookie"] || "";
  const binding = /__Host-dacot_browser=([^;]+)/.exec(cookie)?.[1];
  expect(binding, "Hub must issue its HttpOnly browser binding").toBeTruthy();
  return { api, headers: tabHeaders(binding, tabId) };
}

async function createRestaurant(admin, suffix) {
  const email = `${tag}-${suffix}@example.com`;
  const created = await admin.api.post("/api/hub/tenants", {
    headers: admin.headers,
    data: { name: `E2E ${suffix} ${tag}`, owner_name: "E2E Owner", email, status: "active" },
  });
  expect(created.status()).toBe(200);
  const tenant = await created.json();
  const responsible = await admin.api.post(`/api/hub/tenants/${tenant.id}/users`, {
    headers: admin.headers,
    data: { name: `Responsible ${suffix}`, email: `responsible-${tag}-${suffix}@example.com`, role: "admin", password: EMPLOYEE_PASSWORD },
  });
  expect(responsible.status()).toBe(200);

  const activation = await admin.api.post(`/api/hub/tenants/${tenant.id}/modules/orders/activate`, {
    headers: admin.headers,
  });
  expect(activation.status(), "Pedidos activation must use the local isolated backend").toBe(200);
  const employeeEmail = `employee-${tag}-${suffix}@example.com`;
  const employee = await admin.api.post(`/api/hub/tenants/${tenant.id}/users`, {
    headers: admin.headers,
    data: { name: `Employee ${suffix}`, email: employeeEmail, role: "admin", password: EMPLOYEE_PASSWORD },
  });
  expect(employee.status()).toBe(200);
  const user = await employee.json();
  const launchUrl = await admin.api.patch(`/api/hub/tenants/${tenant.id}/modules/orders`, {
    headers: admin.headers,
    data: { launch_url: `${ORDERS_UI}/${tenant.slug}` },
  });
  expect(launchUrl.status()).toBe(200);
  const grant = await admin.api.put(`/api/hub/tenants/${tenant.id}/modules/orders/users/${user.id}/access`, {
    headers: admin.headers,
    data: { active: true },
  });
  expect(grant.status()).toBe(200);
  return { tenant, user: { ...user, email: employeeEmail } };
}

async function exchangeOrdersSession(employee) {
  const hub = await authenticatedHubApi(employee.email, EMPLOYEE_PASSWORD);
  try {
    const launch = await hub.api.post("/api/portal/modules/orders/launch-token", { headers: hub.headers });
    expect(launch.status()).toBe(200);
    const { handoff } = await launch.json();
    expect(handoff).toBeTruthy();
    const orders = await request.newContext({ baseURL: ORDERS_API, ignoreHTTPSErrors: true });
    try {
      const exchange = await orders.post("/api/orders/session/exchange", { data: { handoff } });
      expect(exchange.status()).toBe(200);
      const body = await exchange.json();
      expect(body.token || body.session_token).toBeTruthy();
      return body.token || body.session_token;
    } finally {
      await orders.dispose();
    }
  } finally {
    await hub.api.dispose();
  }
}

async function ordersBrowserContext(browser, token) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const seedPage = await context.newPage();
  await seedPage.goto(`${ORDERS_UI}/login`);
  await seedPage.evaluate((sessionToken) => {
    window.localStorage.setItem("dacot.token", sessionToken);
  }, token);
  await seedPage.close();
  return context;
}

async function openOrdersPages(browser, token) {
  const context = await ordersBrowserContext(browser, token);
  const dashboard = await context.newPage();
  const orders = await context.newPage();
  const kitchen = await context.newPage();
  await Promise.all([
    dashboard.goto(`${ORDERS_UI}/`),
    orders.goto(`${ORDERS_UI}/pedidos/novo`),
    kitchen.goto(`${ORDERS_UI}/cozinha`),
  ]);
  await expect(dashboard.getByTestId("nav-dashboard")).toBeVisible();
  await expect(orders.getByTestId("nav-new-order")).toBeVisible();
  await expect(kitchen.getByTestId("nav-kitchen")).toBeVisible();
  return { context, dashboard, orders, kitchen };
}

async function deleteEmployeeThroughHubUi(browser, tenant, user, timing) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.origin === HUB_UI && url.pathname.startsWith("/api/")) {
      console.log(`Hub browser response: ${url.pathname} ${response.status()}`);
    }
  });
  await page.goto(`${HUB_UI}/login`);
  await page.getByTestId("login-email").fill(ADMIN_EMAIL);
  await page.getByTestId("login-password").fill(ADMIN_PASSWORD);
  const loginResponse = page.waitForResponse((response) =>
    response.url() === `${HUB_UI}/api/auth/login` && response.request().method() === "POST"
  );
  await page.getByTestId("login-submit").click();
  expect((await loginResponse).status()).toBe(200);
  const browserCookies = await context.cookies(HUB_UI);
  console.log(`Hub browser binding present: ${browserCookies.some((cookie) => cookie.name === "__Host-dacot_browser")}`);
  await expect(page).toHaveURL(/\/painel$/);
  await page.goto(`${HUB_UI}/clientes/${tenant.id}`);
  await expect(page.getByTestId("tenant-detail-page")).toBeVisible();
  await page.getByTestId("tab-users").click();
  await expect(page.getByTestId(`user-row-${user.id}`)).toBeVisible();
  await page.getByTestId(`delete-tenant-user-${user.id}`).click();
  await expect(page.getByText("Excluir funcionário?")).toBeVisible();
  timing.startedAt = Date.now();
  await page.getByTestId(`confirm-delete-tenant-user-${user.id}`).click();
  await expect(page.getByTestId(`user-row-${user.id}`)).toHaveCount(0);
  await context.close();
}

async function hubBrowserPage(browser, email = ADMIN_EMAIL, password = ADMIN_PASSWORD) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  await page.goto(`${HUB_UI}/login`);
  await page.getByTestId("login-email").fill(email);
  await page.getByTestId("login-password").fill(password);
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(/\/painel$/);
  return { context, page };
}

async function waitForLogin(page, name, timing) {
  await page.waitForURL(/\/login(?:\?|$)/, { timeout: 80_000 });
  await expect(page.getByText("Seu acesso ao DACOT foi encerrado.")).toBeVisible();
  evidence.pages[name] = Date.now() - timing.startedAt;
}

test.describe.configure({ mode: "serial" });

test("revoga funcionário em Dashboard, Pedidos e Cozinha sem afetar outro restaurante", async ({ browser }) => {
  const admin = await authenticatedHubApi(ADMIN_EMAIL, ADMIN_PASSWORD);
  try {
    const tenantA = await createRestaurant(admin, "A");
    const tenantB = await createRestaurant(admin, "B");
    const tokenA = await exchangeOrdersSession(tenantA.user);
    const tokenB = await exchangeOrdersSession(tenantB.user);
    const employee = await openOrdersPages(browser, tokenA);
    const unaffected = await ordersBrowserContext(browser, tokenB);
    const unaffectedPage = await unaffected.newPage();
    await unaffectedPage.goto(`${ORDERS_UI}/`);
    await expect(unaffectedPage.getByTestId("nav-dashboard")).toBeVisible();

    const timing = { startedAt: null };
    const disconnects = [
      waitForLogin(employee.dashboard, "dashboard", timing),
      waitForLogin(employee.orders, "orders", timing),
      waitForLogin(employee.kitchen, "kitchen", timing),
    ];
    await deleteEmployeeThroughHubUi(browser, tenantA.tenant, tenantA.user, timing);
    await Promise.all(disconnects);

    const oldToken = await request.newContext({ baseURL: ORDERS_API, ignoreHTTPSErrors: true });
    try {
      const rejected = await oldToken.get("/api/auth/me", { headers: { Authorization: `Bearer ${tokenA}` } });
      expect([401, 403]).toContain(rejected.status());
      evidence.backend.old_token_status = rejected.status();
      const otherSession = await oldToken.get("/api/auth/me", { headers: { Authorization: `Bearer ${tokenB}` } });
      expect(otherSession.status()).toBe(200);
      evidence.backend.other_tenant_status = otherSession.status();
    } finally {
      await oldToken.dispose();
    }
    await expect(unaffectedPage.getByTestId("nav-dashboard")).toBeVisible();
    evidence.backend.other_tenant_remained_authenticated = true;
    evidence.tenant = { id: tenantA.tenant.id, user_id: tenantA.user.id };

    await employee.context.close();
    await unaffected.close();
  } finally {
    await admin.api.dispose();
    fs.writeFileSync(RESULTS_FILE, JSON.stringify(evidence, null, 2));
  }
});

test("revoga sessão ao recuperar conexão após exclusão", async ({ browser }) => {
  const admin = await authenticatedHubApi(ADMIN_EMAIL, ADMIN_PASSWORD);
  let employee;
  try {
    const restaurant = await createRestaurant(admin, "offline");
    const token = await exchangeOrdersSession(restaurant.user);
    employee = await ordersBrowserContext(browser, token);
    const page = await employee.newPage();
    await page.goto(`${ORDERS_UI}/`);
    await expect(page.getByTestId("nav-dashboard")).toBeVisible();
    await employee.setOffline(true);
    await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);

    const timing = { startedAt: null };
    await deleteEmployeeThroughHubUi(browser, restaurant.tenant, restaurant.user, timing);
    const disconnect = waitForLogin(page, "offline_reconnected", timing);
    await employee.setOffline(false);
    await page.bringToFront();
    await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(true);
    await disconnect;
    evidence.backend.offline_reconnected = true;
  } finally {
    if (employee) await employee.close();
    await admin.api.dispose();
    fs.writeFileSync(RESULTS_FILE, JSON.stringify(evidence, null, 2));
  }
});

test("evento sintetico de visibilidade visivel revalida sessao revogada", async ({ browser }) => {
  const admin = await authenticatedHubApi(ADMIN_EMAIL, ADMIN_PASSWORD);
  let employee;
  try {
    const restaurant = await createRestaurant(admin, "visibility-event");
    const token = await exchangeOrdersSession(restaurant.user);
    employee = await ordersBrowserContext(browser, token);
    const page = await employee.newPage();
    await page.goto(`${ORDERS_UI}/`);
    await expect(page.getByTestId("nav-dashboard")).toBeVisible();
    await page.evaluate(() => {
      window.__e2eEvents = { blur: 0, focus: 0, visibilitychange: 0 };
      window.addEventListener("blur", () => window.__e2eEvents.blur++);
      window.addEventListener("focus", () => window.__e2eEvents.focus++);
      document.addEventListener("visibilitychange", () => window.__e2eEvents.visibilitychange++);
    });
    const foreground = await employee.newPage();
    await foreground.bringToFront();
    const timing = { startedAt: null };
    await deleteEmployeeThroughHubUi(browser, restaurant.tenant, restaurant.user, timing);
    await page.bringToFront();
    await expect.poll(() => page.evaluate(() => document.visibilityState)).toBe("visible");
    const observed = await page.evaluate(() => ({ ...window.__e2eEvents, hasFocus: document.hasFocus(), visibility: document.visibilityState }));
    console.log(`Real browser events before synthetic visibilitychange: ${JSON.stringify(observed)}`);
    const revalidation = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.origin === ORDERS_API && url.pathname === "/api/auth/me" && [401, 403].includes(response.status());
    });
    const disconnect = waitForLogin(page, "synthetic_visibility_event", timing);
    // This dispatch tests the existing visible-page handler; it is not evidence
    // that Chromium actually hid a tab or generated a trusted visibility event.
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await revalidation;
    await disconnect;
    evidence.backend.synthetic_visible_event_revalidated = true;
    evidence.backend.real_browser_events = observed;
  } finally {
    if (employee) await employee.close();
    await admin.api.dispose();
    fs.writeFileSync(RESULTS_FILE, JSON.stringify(evidence, null, 2));
  }
});

test.skip("aba realmente oculta: requer ambiente capaz de produzir visibilityState hidden", () => {});

test("handoff pela interface do Portal estabelece sessão no Pedidos", async ({ browser }) => {
  const admin = await authenticatedHubApi(ADMIN_EMAIL, ADMIN_PASSWORD);
  let context;
  try {
    const restaurant = await createRestaurant(admin, "ui-handoff");
    context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();
    await page.goto(`${HUB_UI}/login`);
    await page.getByTestId("login-email").fill(restaurant.user.email);
    await page.getByTestId("login-password").fill(EMPLOYEE_PASSWORD);
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL(/\/portal$/);
    await page.goto(`${HUB_UI}/portal/modulos`);
    await expect(page.getByTestId("portal-module-orders")).toBeVisible();
    const popup = context.waitForEvent("page");
    const exchange = context.waitForEvent("response", { predicate: (response) => {
      const url = new URL(response.url());
      return url.origin === ORDERS_API && url.pathname === "/api/orders/session/exchange" && response.request().method() === "POST";
    } });
    await page.getByTestId("portal-open-orders").click();
    const orders = await popup;
    expect((await exchange).status()).toBe(200);
    await expect(orders.getByTestId("nav-dashboard")).toBeVisible({ timeout: 30_000 });
    expect(await orders.evaluate(() => new URL(window.location.href).searchParams.has("handoff"))).toBe(false);
    await orders.goto(`${ORDERS_UI}/cozinha`);
    await expect(orders.getByTestId("nav-kitchen")).toBeVisible();
    evidence.backend.ui_handoff_completed = true;
  } finally {
    if (context) await context.close();
    await admin.api.dispose();
    fs.writeFileSync(RESULTS_FILE, JSON.stringify(evidence, null, 2));
  }
});

test("exclui restaurante pela interface e invalida sessão sem apagar dados", async ({ browser }) => {
  const admin = await authenticatedHubApi(ADMIN_EMAIL, ADMIN_PASSWORD);
  let employee;
  let hub;
  try {
    const restaurant = await createRestaurant(admin, "deleted-tenant");
    const token = await exchangeOrdersSession(restaurant.user);
    employee = await ordersBrowserContext(browser, token);
    const page = await employee.newPage();
    await page.goto(`${ORDERS_UI}/`);
    await expect(page.getByTestId("nav-dashboard")).toBeVisible();
    hub = await hubBrowserPage(browser);
    await hub.page.goto(`${HUB_UI}/clientes`);
    await expect(hub.page.getByTestId(`tenant-row-${restaurant.tenant.id}`)).toBeVisible();
    await hub.page.getByTestId(`delete-tenant-${restaurant.tenant.id}`).click();
    const timing = { startedAt: Date.now() };
    const disconnect = waitForLogin(page, "deleted_tenant", timing);
    await hub.page.getByTestId("confirm-delete-tenant").click();
    await expect(hub.page.getByTestId(`tenant-row-${restaurant.tenant.id}`)).toHaveCount(0);
    await disconnect;
    const orders = await request.newContext({ baseURL: ORDERS_API });
    try {
      const result = await orders.get("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } });
      expect([401, 403]).toContain(result.status());
    } finally { await orders.dispose(); }
    evidence.deleted_tenant = { id: restaurant.tenant.id, user_id: restaurant.user.id };
  } finally {
    if (hub) await hub.context.close();
    if (employee) await employee.close();
    await admin.api.dispose();
    fs.writeFileSync(RESULTS_FILE, JSON.stringify(evidence, null, 2));
  }
});

test("exclui usuário interno pela interface e protege o próprio super admin", async ({ browser }) => {
  const admin = await authenticatedHubApi(ADMIN_EMAIL, ADMIN_PASSWORD);
  let hub;
  let staff;
  let identity;
  try {
    const email = `staff-${tag}@example.com`;
    const created = await admin.api.post("/api/hub/users", {
      headers: admin.headers,
      data: { name: `E2E Staff ${tag}`, email, role: "admin", password: EMPLOYEE_PASSWORD },
    });
    expect(created.status()).toBe(200);
    const user = await created.json();
    identity = await authenticatedHubApi(email, EMPLOYEE_PASSWORD);
    staff = await hubBrowserPage(browser, email, EMPLOYEE_PASSWORD);
    hub = await hubBrowserPage(browser);
    const self = await admin.api.get("/api/auth/me", { headers: admin.headers });
    expect(self.status()).toBe(200);
    const selfUser = await self.json();
    await hub.page.goto(`${HUB_UI}/equipe`);
    await expect(hub.page.getByTestId(`staff-row-${user.id}`)).toBeVisible();
    await expect(hub.page.getByTestId(`delete-staff-${selfUser.id}`)).toHaveCount(0);
    await hub.page.getByTestId(`delete-staff-${user.id}`).click();
    await hub.page.getByTestId(`confirm-delete-staff-${user.id}`).click();
    await expect(hub.page.getByTestId(`staff-row-${user.id}`)).toHaveCount(0);
    const rejected = await identity.api.get("/api/auth/me", { headers: identity.headers });
    expect(rejected.status()).toBe(401);
    await staff.page.reload();
    await expect(staff.page).toHaveURL(/\/login(?:\?|$)/);
    evidence.deleted_staff = { id: user.id };
    evidence.backend.staff_session_status = rejected.status();
  } finally {
    if (hub) await hub.context.close();
    if (staff) await staff.context.close();
    if (identity) await identity.api.dispose();
    await admin.api.dispose();
    fs.writeFileSync(RESULTS_FILE, JSON.stringify(evidence, null, 2));
  }
});
