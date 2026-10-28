import { test, expect } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { openRequestsWorkspace } from './legacy_navigation.js';

const password = process.env.TVM_DEMO_PASSWORD;
const fixture = fileURLToPath(new URL('./fixtures/warranty_synthetic.xls', import.meta.url));
const marker = () => `GAR-BAT-${Date.now()}-${Math.random().toString(36).slice(2, 7).toUpperCase()}`;

async function login(page, username = 'admin', client = false) {
  if (!password) throw new Error('Utiliser bash scripts/e2e.sh avec le mot de passe local privé.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await expect(page.getByRole('heading', { name: client ? /Tableau de bord|Mon espace/ : 'Tableau de bord', exact: !client }).first()).toBeVisible();
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

async function laboratory(page) {
  const tag = marker();
  const company = await api(page, 'clients/', 'POST', { name: `Laboratoire fictif garantie et batteries ${tag}` });
  const technician = suffix => api(page, 'users/', 'POST', {
    username: `bat-tech-${suffix}-${tag}`, first_name: `Technicien fictif ${suffix}`, role: 'technician', password,
  });
  const techA = await technician('A'), techB = await technician('B');
  const portal = await api(page, 'users/', 'POST', { username: `bat-client-${tag}`, role: 'client', client: company.id, password });
  return { tag, company, techA, techB, portal };
}

async function equipmentAndRequest(page, lab, model, suffix, serial = `SN-${lab.tag}-${suffix}`) {
  const equipment = await api(page, 'equipment/', 'POST', { client: lab.company.id, serial_number: serial, brand: 'Eaton', model });
  const record = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: `${lab.tag} ${suffix}` });
  return { equipment, record };
}

async function dossier(page, record) {
  await openRequestsWorkspace(page);
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(record.reference);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  await page.getByRole('button', { name: `Ouvrir ${record.reference}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Dossier SAV', exact: true });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function claim(page, dialog, record) {
  await dialog.getByRole('button', { name: 'Prendre en charge', exact: true }).click();
  const confirmation = page.getByRole('alertdialog', { name: 'Prendre en charge', exact: true });
  const saved = page.waitForResponse(result => new URL(result.url()).pathname === `/api/requests/${record.id}/assignment/claim/` && result.request().method() === 'POST');
  await confirmation.getByRole('button', { name: 'Oui', exact: true }).click();
  const result = await saved;
  expect(result.status(), await result.text()).toBe(200);
  await expect(confirmation).toHaveCount(0);
  return result.json();
}

async function followup(page, dialog, record, observation) {
  await dialog.getByLabel('Observation', { exact: true }).fill(observation);
  const saved = page.waitForResponse(result => new URL(result.url()).pathname === `/api/requests/${record.id}/followup/` && result.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Enregistrer le suivi', exact: true }).click();
  const result = await saved;
  expect(result.status(), await result.text()).toBe(201);
  await expect(dialog.getByRole('region', { name: 'Historique des opérations', exact: true })).toContainText(observation);
  return { data: await result.json(), payload: result.request().postDataJSON() };
}

async function checkWarranty(page, dialog, refresh = false) {
  const loaded = page.waitForResponse(result => new URL(result.url()).pathname === '/api/serial-lookup/' && result.request().method() === 'POST');
  await dialog.getByRole('button', { name: refresh ? 'Actualiser la garantie' : 'Vérifier la garantie', exact: true }).click();
  const result = await loaded;
  expect(result.status(), await result.text()).toBe(200);
  await expect(dialog.locator('.warranty-check')).toBeVisible();
  return result.json();
}

async function cardContrast(card) {
  const violations = await card.evaluate(root => {
    const rgba = value => {
      const match = value.match(/^rgba?\(([^)]+)\)$/);
      if (!match) return null;
      const values = match[1].split(/[\s,/]+/).filter(Boolean).map(Number);
      return [values[0], values[1], values[2], values[3] ?? 1];
    };
    const over = (a, b) => [0, 1, 2].map(i => a[i] * a[3] + b[i] * (1 - a[3])).concat(1);
    const luminance = color => color.slice(0, 3).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
    const issues = [];
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walk.nextNode())) {
      const text = node.textContent.trim(), element = node.parentElement;
      if (!text || !element || element.closest('svg,script,style,[hidden],[aria-hidden="true"]')) continue;
      const range = document.createRange(); range.selectNodeContents(node);
      if (![...range.getClientRects()].some(rect => rect.width > 0 && rect.height > 0)) continue;
      let background = [255, 255, 255, 1];
      const ancestors = [];
      for (let item = element; item; item = item.parentElement) ancestors.unshift(item);
      if (ancestors.some(item => getComputedStyle(item).visibility !== 'visible' || getComputedStyle(item).display === 'none')) continue;
      for (const item of ancestors) { const color = rgba(getComputedStyle(item).backgroundColor); if (color) background = over(color, background); }
      const foreground = rgba(getComputedStyle(element).color);
      if (!foreground) continue;
      const a = luminance(over(foreground, background)), b = luminance(background);
      const ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      if (ratio < 4.5) issues.push({ text: text.slice(0, 80), ratio: Number(ratio.toFixed(2)) });
    }
    return issues;
  });
  expect(violations).toEqual([]);
}

test('la garantie catalogue G2 applique six mois calendaires et les dates réellement enregistrées restent prioritaires sans réécriture', async ({ page }) => {
  await login(page);
  const lab = await laboratory(page);
  const { csrfToken } = await (await page.request.get('/api/session/')).json();
  const imported = await page.request.post('/api/catalogue/import/', { headers: { 'X-CSRFToken': csrfToken }, multipart: { file: { name: 'warranty_synthetic.xls', mimeType: 'application/vnd.ms-excel', buffer: (await import('node:fs')).readFileSync(fixture) } } });
  expect([200, 201], await imported.text()).toContain(imported.status());
  let serial;
  for (let offset = 0; offset < 20; offset += 1) {
    serial = `GWG2A49${String((Date.now() + offset) % 1000).padStart(3, '0')}`;
    if ((await api(page, `equipment/?serial=${serial}`)).length === 0) break;
  }
  const data = await equipmentAndRequest(page, lab, 'LAB-WAR-G2', 'GARANTIE', serial);
  await page.reload();
  const dialog = await dossier(page, data.record);
  const lookup = await checkWarranty(page, dialog);
  expect(lookup.warranty_check).toMatchObject({ basis: 'catalogue', status: 'expired', manufactured_on: '2023-12-04',
    starts_on: '2024-06-04', ends_on: '2026-06-04', duration_months: 24,
    commercial_part_number: 'LAB-WAR-G2', industrial_part_number: 'LAB-IND-WAR',
    source: { warranty_match_type: 'generation_family' } });
  const card = dialog.locator('.warranty-check');
  await expect(card).toContainText('Garantie expirée');
  await expect(card).toContainText('Gen 2');
  for (const date of ['04/12/2023', '04/06/2024', '04/06/2026']) await expect(card).toContainText(date);
  await expect(card).toContainText('non jour de fabrication certifié');
  expect(await api(page, `equipment/${data.equipment.id}/`)).toEqual(data.equipment);
  const real = await api(page, 'warranties/', 'POST', { equipment: data.equipment.id, scope: 'electronics_and_batteries',
    starts_on: '2026-01-01', ends_on: '2027-12-31', provider: 'Garantie réellement enregistrée de laboratoire' });
  const actual = await checkWarranty(page, dialog, true);
  expect(actual.warranty_check).toMatchObject({ basis: 'recorded', status: 'active', starts_on: real.starts_on, ends_on: real.ends_on });
  expect(actual.catalogue_computed_warranty).toMatchObject({ starts_on: '2024-06-04', ends_on: '2026-06-04', coverage_status: 'expired' });
  await expect(card).toContainText('Garantie enregistrée');
  await expect(card).toContainText('Garantie en cours');
  await expect(card).toContainText('01/01/2026');
  await expect(card).toContainText('31/12/2027');
  expect(await api(page, `warranties/${real.id}/`)).toEqual(real);
  expect(await api(page, `equipment/${data.equipment.id}/`)).toEqual(data.equipment);
  await page.setViewportSize({ width: 390, height: 844 });
  await cardContrast(card);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await card.screenshot({ path: '../../.local/warranty-card-mobile.png' });
});

test('le nominal batterie suit l’acceptation, le comptage réel exige un accord explicite et les anciennes fiches restent conservées', async ({ page, browser }) => {
  await login(page);
  const lab = await laboratory(page);
  // This is a public model alias from the user-supplied battery table, with an invented serial.
  const data = await equipmentAndRequest(page, lab, '5E700FG2', 'COMPTAGE');
  const context = await browser.newContext(), clientContext = await browser.newContext();
  const tech = await context.newPage(), client = await clientContext.newPage();
  try {
    await login(tech, lab.techA.username);
    const dialog = await dossier(tech, data.record);
    await expect(dialog.locator('.battery-configuration')).toHaveCount(0);
    expect((await response(tech, `requests/${data.record.id}/followup/`, 'POST', { status: 'new', expected_status: 'new', assignment_revision: 0, observation: 'Avant prise en charge', battery_count: 3 })).status()).toBe(403);
    const accepted = await claim(tech, dialog, data.record);
    expect(accepted).toMatchObject({ battery_count: 1, battery_count_source: 'reference', battery_configuration: { status: 'matched', nominal_count: 1 } });
    const card = dialog.locator('.battery-configuration');
    await expect(card).toContainText('Prérempli depuis la référence');
    await expect(dialog.getByLabel('Nombre réel de batteries', { exact: true })).toHaveValue('1');
    const observation = await followup(tech, dialog, data.record, `${lab.tag} observation sans comptage`);
    expect(observation.payload).not.toHaveProperty('battery_count');
    expect(observation.data.request.battery_count_source).toBe('reference');
    await dialog.getByRole('checkbox', { name: 'J’ai vérifié le nombre de batteries sur ce matériel', exact: true }).check();
    const same = await followup(tech, dialog, data.record, `${lab.tag} comptage physique explicitement identique`);
    expect(same.payload.battery_count).toBe(1);
    expect(same.data.request.battery_count_source).toBe('manual');
    const oldVisit = await api(page, 'interventions/', 'POST', { service_request: data.record.id, technician: lab.techA.id,
      status: 'in_progress', battery_count: 7, work_done: 'Ancienne quantité fictive, à conserver' });
    await dialog.getByLabel('Nombre réel de batteries', { exact: true }).fill('2');
    await dialog.getByRole('checkbox', { name: 'J’ai vérifié le nombre de batteries sur ce matériel', exact: true }).check();
    const changed = await followup(tech, dialog, data.record, `${lab.tag} deux batteries constatées`);
    expect(changed.data.request).toMatchObject({ battery_count: 2, battery_count_source: 'manual' });
    expect((await api(page, `interventions/${oldVisit.id}/`)).battery_count).toBe(7);
    const newVisit = await api(tech, 'interventions/', 'POST', { service_request: data.record.id, status: 'in_progress', work_done: 'Nouvelle fiche après comptage confirmé' });
    expect(newVisit.battery_count).toBe(2);
    await tech.setViewportSize({ width: 390, height: 844 });
    await cardContrast(card);
    expect(await tech.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await card.screenshot({ path: '../../.local/battery-card-mobile.png' });
    const current = await api(page, `requests/${data.record.id}/`);
    await api(page, `requests/${data.record.id}/assignment/`, 'POST', { technician: lab.techB.id, expected_revision: current.assignment.revision });
    expect((await response(tech, `requests/${data.record.id}/followup/`, 'POST', { status: current.status, expected_status: current.status,
      assignment_revision: current.assignment.revision, observation: 'Comptage périmé interdit', battery_count: 99 })).status()).toBe(403);
    expect((await api(page, `requests/${data.record.id}/`)).battery_count).toBe(2);
    await login(client, lab.portal.username, true);
    const publicRecord = await api(client, `requests/${data.record.id}/`);
    for (const key of ['battery_count', 'battery_count_source', 'battery_configuration']) expect(publicRecord).not.toHaveProperty(key);
    const history = await api(client, `requests/${data.record.id}/timeline/`);
    expect(history.some(event => ['battery_count', 'battery_reference'].includes(event.kind))).toBe(false);
  } finally { await Promise.all([context.close(), clientContext.close()]); }
});

test('zéro batterie interne ne devient pas un total installé nul et une référence inconnue permet un comptage manuel', async ({ page, browser }) => {
  await login(page);
  const lab = await laboratory(page);
  const external = await equipmentAndRequest(page, lab, '9E11000IR', 'EXTERNE');
  const unknown = await equipmentAndRequest(page, lab, 'Onduleur de laboratoire 750VA', 'INCONNU');
  const context = await browser.newContext();
  const tech = await context.newPage();
  try {
    await login(tech, lab.techA.username);
    let dialog = await dossier(tech, external.record);
    const accepted = await claim(tech, dialog, external.record);
    expect(accepted).toMatchObject({ battery_count: null, battery_count_source: '', battery_configuration: { nominal_count: 0, external_battery_required: true } });
    await expect(dialog.locator('.battery-configuration')).toContainText('le total installé');
    await expect(dialog.getByLabel('Nombre réel de batteries', { exact: true })).toHaveValue('');
    const unchanged = await followup(tech, dialog, external.record, `${lab.tag} armoire externe à contrôler`);
    expect(unchanged.data.request.battery_count).toBeNull();
    await dialog.getByRole('button', { name: 'Fermer', exact: true }).first().click();
    dialog = await dossier(tech, unknown.record);
    const unidentified = await claim(tech, dialog, unknown.record);
    expect(unidentified).toMatchObject({ battery_count: null, battery_configuration: { status: 'unknown', nominal_count: null } });
    await expect(dialog.locator('.battery-configuration')).toContainText('Aucune quantité nominale');
    await dialog.getByLabel('Nombre réel de batteries', { exact: true }).fill('3');
    await dialog.getByRole('checkbox', { name: 'J’ai vérifié le nombre de batteries sur ce matériel', exact: true }).check();
    const manual = await followup(tech, dialog, unknown.record, `${lab.tag} trois batteries constatées sur le modèle non identifié`);
    expect(manual.data.request).toMatchObject({ battery_count: 3, battery_count_source: 'manual', battery_configuration: { status: 'unknown' } });
  } finally { await context.close(); }
});
