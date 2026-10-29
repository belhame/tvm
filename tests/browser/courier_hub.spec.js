import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { acceptCurrentOutboundMission } from './legacy_navigation.js';

const password = process.env.TVM_DEMO_PASSWORD;
const marker = () => `HUB-FICTIF-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

async function login(page, username = 'admin', courier = false) {
  if (!password) throw new Error('Utiliser bash scripts/e2e.sh avec le mot de passe E2E privé.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  await page.getByRole('button', { name: /Se connecter/i }).click();
  if (courier) await expect(page.getByRole('navigation', { name: 'Navigation livreur', exact: true })).toBeVisible();
  else await expect(page.getByRole('heading', { name: 'Tableau de bord', exact: true })).toBeVisible();
}

async function response(page, path, method = 'GET', data) {
  const { csrfToken } = await (await page.request.get('/api/session/')).json();
  return page.request.fetch(`/api/${path}`, { method, data, headers: { 'X-CSRFToken': csrfToken } });
}

async function api(page, path, method = 'GET', data) {
  const result = await response(page, path, method, data);
  expect(result.ok(), `${method} ${path}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

async function unit(page, company, serial) {
  return api(page, 'equipment/', 'POST', { client: company.id, serial_number: serial, brand: 'Eaton', model: 'Onduleur de laboratoire fictif' });
}

async function ready(page, company, tag) {
  const equipment = await unit(page, company, `${tag}-SERIE`);
  const record = await api(page, 'requests/', 'POST', {
    equipment: equipment.id, status: 'testing', subject: `Essais fictifs ${tag}`, client_reference: `000-${tag}`,
  });
  const { as_of: tested_on } = await api(page, 'requests/categories/');
  const saved = await api(page, `requests/${record.id}/disposition/repair/`, 'POST', {
    diagnosis: 'Essais de fonctionnement fictifs confirmés au laboratoire.', tests_passed: true, tested_on,
  });
  return { equipment, record: saved };
}

async function pickup(page, company, courier, tag) {
  const equipment = await unit(page, company, `${tag}-COLLECTE`);
  const record = await api(page, 'logistics/pickups/', 'POST', {
    request_key: randomUUID(), client: company.id, equipment: equipment.id,
    fault_description: 'Signalement fictif avant collecte.', pickup_address: 'Adresse fictive de collecte',
    contact_name: 'Contact fictif', contact_phone: '0000000000',
  });
  return api(page, `logistics/pickups/${record.id}/assign/`, 'POST', { courier: courier.id });
}

test('le livreur arrive sur À livrer puis sépare ses collectes des livraisons et un livreur client ne voit que ses missions', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker();
  const companyA = await api(page, 'clients/', 'POST', { name: `Centre fictif A ${tag}`, notes: `NOTE-PRIVEE-A-${tag}` });
  const companyB = await api(page, 'clients/', 'POST', { name: `Centre fictif B ${tag}`, notes: `NOTE-PRIVEE-B-${tag}` });
  const driver = await api(page, 'users/', 'POST', { username: `hub-tvm-${tag}`, first_name: 'Livreur TVM fictif', role: 'courier', password });
  const other = await api(page, 'users/', 'POST', { username: `hub-autre-${tag}`, first_name: 'Autre livreur fictif', role: 'courier', password });
  const external = await api(page, 'users/', 'POST', {
    username: `hub-client-${tag}`, first_name: 'Livreur client fictif', role: 'courier', courier_kind: 'client', client: companyA.id, password,
  });
  const availableA = await ready(page, companyA, `${tag}-DISPO-A`);
  const availableB = await ready(page, companyB, `${tag}-DISPO-B`);
  const own = await ready(page, companyA, `${tag}-PROPRE`);
  const foreign = await ready(page, companyB, `${tag}-AUTRE`);
  const externalUnit = await ready(page, companyA, `${tag}-EXTERNE`);
  const ownJob = await api(page, 'logistics/outbound/', 'POST', { service_request: own.record.id, courier: driver.id });
  await api(page, 'logistics/outbound/', 'POST', { service_request: foreign.record.id, courier: other.id });
  const externalJob = await api(page, 'logistics/outbound/', 'POST', { service_request: externalUnit.record.id, courier: external.id });
  const returnedEquipment = await unit(page, companyA, `${tag}-RETOUR`);
  const returned = await api(page, 'requests/', 'POST', { equipment: returnedEquipment.id, subject: `Retour fictif ${tag}`, status: 'testing' });
  await api(page, `requests/${returned.id}/disposition/nonrepairable/`, 'POST', { diagnosis: 'Matériel fictif non réparable ; diagnostic encore à facturer.', fee_mode: 'billable' });
  const returnJob = await api(page, 'logistics/outbound/', 'POST', { service_request: returned.id, courier: driver.id });
  const ownPickup = await pickup(page, companyA, driver, `${tag}-PROPRE`);
  const foreignPickup = await pickup(page, companyB, other, `${tag}-AUTRE`);
  const courierContext = await browser.newContext(), externalContext = await browser.newContext();
  const courier = await courierContext.newPage(), clientDriver = await externalContext.newPage();
  const externalRequests = [];
  clientDriver.on('request', request => externalRequests.push(new URL(request.url()).pathname));
  try {
    await login(courier, driver.username, true);
    await expect(courier.getByRole('heading', { name: 'À livrer', exact: true })).toBeVisible();
    const transports = courier.getByRole('region', { name: 'Navigation des transports', exact: true });
    await expect(transports.getByRole('button', { name: /^À livrer/ })).toBeVisible();
    await expect(transports.getByRole('button', { name: /^À récupérer/ })).toBeVisible();
    await expect(courier.getByRole('heading', { name: 'Mes livraisons', exact: true })).toBeVisible();
    const ownCard = courier.locator('.courier-job-card').filter({ hasText: own.equipment.serial_number });
    await expect(ownCard).toBeVisible();
    await expect(courier.locator('.courier-job-card').filter({ hasText: returnedEquipment.serial_number })).toContainText('Retour client');
    await expect(courier.locator('.courier-job-card').filter({ hasText: ownPickup.serial_number })).toHaveCount(0);
    await expect(courier.locator('.courier-job-card').filter({ hasText: foreign.equipment.serial_number })).toHaveCount(0);
    for (const fixture of [availableA, availableB])
      await expect(courier.locator('.courier-ready-card').filter({ hasText: fixture.equipment.serial_number })).toBeVisible();
    const accepted = await acceptCurrentOutboundMission(courier, ownCard, ownJob);
    expect(accepted.handed_over_at).toBeNull();
    await transports.getByRole('button', { name: /^À récupérer/ }).click();
    await expect(courier.getByRole('heading', { name: 'À récupérer', exact: true })).toBeVisible();
    await expect(courier.getByRole('heading', { name: 'Mes enlèvements', exact: true })).toBeVisible();
    await expect(courier.locator('.courier-job-card').filter({ hasText: ownPickup.serial_number })).toBeVisible();
    await expect(courier.locator('.courier-job-card').filter({ hasText: foreignPickup.serial_number })).toHaveCount(0);
    await expect(courier.locator('.courier-job-card').filter({ hasText: own.equipment.serial_number })).toHaveCount(0);
    await courier.setViewportSize({ width: 390, height: 844 });
    const mobileCard = courier.locator('.courier-job-card').filter({ hasText: ownPickup.serial_number });
    await mobileCard.scrollIntoViewIfNeeded();
    const bounds = await mobileCard.evaluate(element => ({ left: element.getBoundingClientRect().left,
      right: element.getBoundingClientRect().right, viewport: innerWidth,
      scroll: element.scrollWidth, width: element.clientWidth }));
    expect(bounds.left).toBeGreaterThanOrEqual(0);
    expect(bounds.right).toBeLessThanOrEqual(bounds.viewport);
    expect(bounds.scroll).toBeLessThanOrEqual(bounds.width + 2);
    await courier.screenshot({ path: '../../.local/courier-hub-mobile-viewport.png' });
    expect((await api(page, `logistics/pickups/${ownPickup.id}/`))).toMatchObject({ service_request: null, received_at: null, status: 'assigned' });
    expect((await api(page, `requests/${returned.id}/`))).toMatchObject({ status: 'return_to_client', closed_at: null, disposition: { finance_validated_at: null } });
    expect((await api(page, `logistics/outbound/${returnJob.id}/`))).toMatchObject({ handed_over_at: null, accepted: false });

    await login(clientDriver, external.username, true);
    await expect(clientDriver.getByRole('heading', { name: 'À livrer', exact: true })).toBeVisible();
    await expect(clientDriver.locator('.courier-job-card').filter({ hasText: externalUnit.equipment.serial_number })).toBeVisible();
    await expect(clientDriver.getByRole('button', { name: /^À récupérer/ })).toHaveCount(0);
    await expect(clientDriver.locator('.courier-ready-card')).toHaveCount(0);
    expect(externalRequests).not.toContain('/api/logistics/pickups/');
    expect(externalRequests).not.toContain('/api/logistics/ready-queue/');
    const scopedJobs = await api(clientDriver, 'logistics/outbound/');
    expect(scopedJobs.map(job => job.id)).toEqual([externalJob.id]);
    expect(JSON.stringify(scopedJobs)).not.toContain(companyA.notes);
    expect(JSON.stringify(scopedJobs)).not.toContain(companyB.name);
    expect(await api(clientDriver, 'logistics/pickups/')).toEqual([]);
    for (const path of ['repair-quotes/', 'logistics/ready-queue/', 'requests/'])
      expect((await response(clientDriver, path)).status()).toBe(403);
  } finally { await Promise.all([courierContext.close(), externalContext.close()]); }
});
