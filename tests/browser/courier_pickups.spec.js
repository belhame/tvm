import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const password = process.env.TVM_DEMO_PASSWORD;
const fixturePath = name => fileURLToPath(new URL(`../../backend/core/tests/fixtures/${name}`, import.meta.url));

async function login(page, username = 'admin', courier = false) {
  if (!password) throw new Error('TVM_DEMO_PASSWORD requis ; utiliser bash scripts/e2e.sh.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const path = courier ? '/api/logistics/bootstrap/' : '/api/dashboard/';
  const loaded = page.waitForResponse(result => new URL(result.url()).pathname === path && result.ok());
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  if (courier) await expect(page.getByRole('navigation', { name: 'Navigation livreur', exact: true })).toBeVisible();
  else await expect(page.locator('.metric-value').first()).toContainText(/\d/);
}

async function response(page, path, method = 'GET', data) {
  const { csrfToken } = await (await page.request.get('/api/session/')).json();
  return page.request.fetch(`/api/${path}`, { method, data, headers: { 'X-CSRFToken': csrfToken } });
}

async function api(page, path, method = 'GET', data) {
  const result = await response(page, path, method, data);
  expect(result.ok(), `${method} ${path} → ${result.status()}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

async function mutation(pending) {
  const result = await pending;
  expect(result.ok(), `${result.status()}: ${await result.text()}`).toBeTruthy();
  return { result, data: await result.json() };
}

function mutationResponse(page, path) {
  return page.waitForResponse(result => new URL(result.url()).pathname === `/api/${path}` && result.request().method() === 'POST');
}

async function navigate(page, label) {
  const navigation = page.getByRole('navigation', { name: 'Navigation principale' });
  if (!await navigation.isVisible()) await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await navigation.getByText(label, { exact: true }).click();
}

async function courierNavigate(page, label) {
  await page.getByRole('navigation', { name: 'Navigation livreur', exact: true }).getByRole('button', { name: label, exact: true }).click();
}

async function courierReload(page) {
  const loaded = page.waitForResponse(result => new URL(result.url()).pathname === '/api/logistics/bootstrap/' && result.ok());
  await page.reload();
  await loaded;
}

function marker(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

async function courierAccount(page, tag) {
  return api(page, 'users/', 'POST', { username: `livreur-${tag}`, first_name: 'Livreur fictif', role: 'courier', password });
}

async function owner(page, tag) {
  return api(page, 'clients/', 'POST', {
    name: `Laboratoire logistique fictif ${tag}`, contact_name: 'Contact fictif du laboratoire',
    address: 'Adresse de laboratoire uniquement', city: 'Cotonou', phone: '0000001234',
    notes: `NOTE-CLIENT-INTERNE-${tag}`, tax_id: `000-FISC-${tag}`,
  });
}

async function equipment(page, company, serial, model = 'Onduleur fictif de transport') {
  return api(page, 'equipment/', 'POST', { client: company.id, serial_number: serial, model, brand: 'Eaton' });
}

async function clientAccount(page, company, tag) {
  return api(page, 'users/', 'POST', { username: `client-logistique-${tag}`, role: 'client', client: company.id, password });
}

function physicalReception(page) {
  return page.getByRole('region', { name: 'Réception physique d’un onduleur', exact: true });
}

function assertServerTimestamp(value, before, after = Date.now()) {
  expect(typeof value).toBe('string');
  const recorded = Date.parse(value);
  expect(Number.isNaN(recorded)).toBe(false);
  expect(recorded).toBeGreaterThanOrEqual(before - 1000);
  expect(recorded).toBeLessThanOrEqual(after + 1000);
}

// The same rendered-text calculation as the main contrast regression, scoped to the courier surface.
async function expectCourierContrast(page, surface) {
  await page.evaluate(() => document.fonts.ready);
  const findings = await page.evaluate(() => {
    const root = document.querySelector('[role="dialog"]') || document.querySelector('.courier-app') || document.body;
    const violations = [];
    const unsupported = [];
    const parse = value => {
      const match = value.match(/^rgba?\(([^)]+)\)$/);
      if (!match) return null;
      const parts = match[1].split(/[\s,/]+/).filter(Boolean).map(Number);
      return [parts[0], parts[1], parts[2], parts[3] ?? 1];
    };
    const over = (top, bottom) => {
      const alpha = top[3] + bottom[3] * (1 - top[3]);
      return [0, 1, 2].map(index => (top[index] * top[3] + bottom[index] * bottom[3] * (1 - top[3])) / alpha).concat(alpha);
    };
    const luminance = color => color.slice(0, 3).map(channel => {
      const value = channel / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    }).reduce((total, channel, index) => total + channel * [0.2126, 0.7152, 0.0722][index], 0);
    const ratio = (foreground, background) => {
      const a = luminance(over(foreground, background));
      const b = luminance(background);
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    };
    const inViewport = rect => rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight;
    const rendered = element => {
      if (element.closest('script, style, svg, .sr-only, [aria-hidden="true"], [hidden], :disabled')) return false;
      if (![...element.getClientRects()].some(inViewport)) return false;
      for (let item = element; item; item = item.parentElement) {
        const style = getComputedStyle(item);
        if (style.visibility !== 'visible' || style.display === 'none' || Number(style.opacity) === 0) return false;
      }
      return true;
    };
    const backgrounds = element => {
      const ancestors = [];
      for (let item = element; item; item = item.parentElement) ancestors.unshift(item);
      let colors = [[255, 255, 255, 1]];
      for (const ancestor of ancestors) {
        const style = getComputedStyle(ancestor);
        const solid = parse(style.backgroundColor);
        if (solid && solid[3]) colors = colors.map(color => over(solid, color));
        if (style.backgroundImage !== 'none') {
          // Every gradient stop must pass: this catches pale ends of buttons,
          // rather than evaluating only their nominal backgroundColor.
          if (!/gradient\(/.test(style.backgroundImage) || /url\(/.test(style.backgroundImage)) return null;
          const stops = (style.backgroundImage.match(/rgba?\([^)]+\)/g) || []).map(parse).filter(Boolean);
          if (!stops.length) return null;
          colors = colors.flatMap(color => stops.map(stop => over(stop, color)));
        }
      }
      return colors;
    };
    const checked = new Set();
    let count = 0;
    const check = (element, text, pseudo = null) => {
      if (!text.trim() || !rendered(element)) return;
      const style = getComputedStyle(element, pseudo);
      const size = Number.parseFloat(style.fontSize);
      const weight = Number.parseInt(style.fontWeight, 10) || 400;
      if (size >= 24 || size >= 18.6667 && weight >= 700) return;
      const foreground = parse(style.color);
      if (!foreground || !foreground[3]) return;
      const key = `${element.tagName}.${element.className}|${style.color}|${text.trim().slice(0, 100)}|${pseudo}`;
      if (checked.has(key)) return;
      checked.add(key);
      let opacity = 1;
      for (let item = element; item; item = item.parentElement) opacity *= Number(getComputedStyle(item).opacity);
      foreground[3] *= opacity * Number(style.opacity || 1) / Number(getComputedStyle(element).opacity || 1);
      const colors = backgrounds(element);
      if (!colors) {
        unsupported.push({ text: text.trim().slice(0, 80), element: element.tagName, className: String(element.className) });
        return;
      }
      count += 1;
      const lowest = Math.min(...colors.map(background => ratio(foreground, background)));
      if (lowest < 4.5) violations.push({
        text: text.trim().slice(0, 100), element: element.tagName, className: String(element.className),
        color: style.color, background: getComputedStyle(element).backgroundColor,
        ratio: Math.round(lowest * 1000) / 1000, fontSize: style.fontSize,
      });
    };
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const element = node.parentElement;
      const range = document.createRange();
      range.selectNodeContents(node);
      if (element && [...range.getClientRects()].some(inViewport)) check(element, node.textContent || '');
    }
    for (const element of root.querySelectorAll('input:not([type="password"]), textarea, select')) {
      if (element.tagName === 'SELECT') check(element, element.selectedOptions[0]?.textContent || '');
      else if (element.value) check(element, element.value);
      else if (element.placeholder) check(element, element.placeholder, '::placeholder');
    }
    return { count, violations, unsupported };
  });
  expect(findings.count, `${surface} : aucun texte normal vérifié`).toBeGreaterThan(3);
  expect(findings.unsupported, `${surface} : fond impossible à vérifier avec les styles calculés`).toEqual([]);
  expect(findings.violations, `${surface} : contraste de texte inférieur à 4,5:1`).toEqual([]);
}

test('le livreur utilise son espace dédié et la douchette prépare une réception serveur explicite, idempotente et sans affectation technique', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('reception-fictive');
  const company = await owner(page, tag);
  const unit = await equipment(page, company, `SN-000042-${tag}`);
  const account = await courierAccount(page, tag);
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const courier = await context.newPage();
  const oldApiCalls = [];
  const receptions = [];
  courier.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (/^\/api\/(dashboard|clients|equipment|requests|interventions|users|parts|contracts|audit|search)(?:\/|$)/.test(path)) oldApiCalls.push(path);
    if (path === '/api/logistics/receive/' && request.method() === 'POST') receptions.push(request);
  });
  try {
    await login(courier, account.username, true);
    const bootstrap = await api(courier, 'logistics/bootstrap/');
    expect(bootstrap.user.role).toBe('courier');
    expect(bootstrap.couriers).toEqual([]);
    for (const client of bootstrap.clients) expect(Object.keys(client).sort()).toEqual(['id', 'name']);
    await expect(courier.locator('.courier-metrics .metric-value')).toHaveText([String(bootstrap.metrics.pickups), String(bootstrap.metrics.ready), String(bootstrap.metrics.returns)]);
    await expectCourierContrast(courier, 'Accueil livreur mobile');
    expect(await courier.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)).toBe(false);
    for (const path of ['dashboard/', 'clients/', 'equipment/', 'requests/', 'interventions/', 'users/', 'parts/', 'audit/', 'search/?q=secret', 'interventions/1/report/', 'requests/1/documents/', 'diagnostic-quotes/1/pdf/'])
      expect((await response(courier, path)).status(), `API interne refusée : ${path}`).toBe(403);
    expect((await courier.request.get('/admin/')).status()).toBe(403);
    await courierNavigate(courier, 'Réception');
    const reception = physicalReception(courier);
    await reception.getByRole('button', { name: 'Douchette USB / Bluetooth', exact: true }).click();
    const serial = reception.getByRole('textbox', { name: 'Numéro de série à réceptionner', exact: true });
    await serial.fill(unit.serial_number);
    const searched = mutationResponse(courier, 'logistics/lookup/');
    await serial.press('Enter');
    const lookup = await mutation(searched);
    expect(lookup.data).toMatchObject({ status: 'known', equipment: { id: unit.id, client: { id: company.id }, model: unit.model } });
    expect(receptions).toHaveLength(0);
    expect(await api(page, `requests/?q=${encodeURIComponent(unit.serial_number)}`)).toEqual([]);
    await expect(reception).toContainText(unit.model);
    await expect(reception.getByRole('combobox', { name: 'Client propriétaire', exact: true })).toBeDisabled();
    const confirm = reception.getByRole('button', { name: 'Confirmer la réception', exact: true });
    await expect(confirm).toBeDisabled();
    await reception.getByRole('textbox', { name: 'N° d’appel client / référence client', exact: true }).fill(`000-RECEP-${tag}`);
    await reception.getByRole('textbox', { name: 'Motif signalé', exact: true }).fill('Contrôle fictif demandé à la réception.');
    await reception.getByRole('checkbox', { name: 'Je confirme avoir reçu physiquement cet onduleur.', exact: true }).check();
    const before = Date.now();
    const receivedResponse = mutationResponse(courier, 'logistics/receive/');
    await confirm.click();
    const received = await mutation(receivedResponse);
    const receipt = received.data;
    expect(receipt).toMatchObject({ created_request: true, created_equipment: false, already_received: false, request: { serial_number: unit.serial_number, status: 'new', client_reference: `000-RECEP-${tag}`, client: { id: company.id } } });
    assertServerTimestamp(receipt.request.arrived_at, before);
    const posted = received.result.request().postDataJSON();
    expect(posted.source).toBe('usb');
    expect(Object.hasOwn(posted, 'arrived_at')).toBe(false);
    const saved = await api(page, `requests/${receipt.request.id}/`);
    expect(saved).toMatchObject({ status: 'new', assigned_technician: null, equipment: unit.id });
    expect(Date.parse(saved.arrived_at)).toBe(Date.parse(receipt.request.arrived_at));
    expect(saved.timing.timer_state).toBe('running');
    await expect(reception.getByRole('heading', { name: 'Réception confirmée', exact: true })).toBeVisible();
    const replay = await api(courier, 'logistics/receive/', 'POST', posted);
    expect(replay.receipt_id).toBe(receipt.receipt_id);
    expect(replay.request.id).toBe(receipt.request.id);
    await api(page, `requests/${receipt.request.id}/`, 'PATCH', { status: 'quotation' });
    const already = await api(courier, 'logistics/receive/', 'POST', { ...posted, request_key: randomUUID() });
    expect(already).toMatchObject({ created_request: false, already_received: true, request: { id: receipt.request.id, status: 'quotation' } });
    expect(Date.parse(already.request.arrived_at)).toBe(Date.parse(receipt.request.arrived_at));
    expect(await api(page, `requests/?q=${encodeURIComponent(unit.serial_number)}`)).toHaveLength(1);

    await reception.getByRole('button', { name: 'Nouvelle réception', exact: true }).click();
    const unknownSerial = `INCONNU-000007-${tag}`.toUpperCase();
    await reception.getByRole('textbox', { name: 'Numéro de série à réceptionner', exact: true }).fill(unknownSerial);
    const unknownLookup = mutationResponse(courier, 'logistics/lookup/');
    await reception.getByRole('button', { name: 'Rechercher le matériel', exact: true }).click();
    expect((await mutation(unknownLookup)).data.status).toBe('unknown');
    await reception.getByRole('textbox', { name: 'Modèle manuel de l’onduleur', exact: true }).fill('Modèle fictif vérifié sur l’étiquette');
    await reception.getByRole('textbox', { name: 'Marque du matériel', exact: true }).fill('Marque fictive');
    await reception.getByRole('combobox', { name: 'Client propriétaire', exact: true }).selectOption(String(company.id));
    const physical = reception.getByRole('checkbox', { name: 'Je confirme avoir reçu physiquement cet onduleur.', exact: true });
    await physical.check();
    await expect(reception.getByRole('button', { name: 'Confirmer la réception', exact: true })).toBeDisabled();
    await reception.getByRole('textbox', { name: 'Justification du modèle manuel', exact: true }).fill('Identification fictive saisie après lecture manuelle de l’étiquette.');
    await expect(physical).not.toBeChecked();
    await physical.check();
    const unknownReceipt = mutationResponse(courier, 'logistics/receive/');
    await reception.getByRole('button', { name: 'Confirmer la réception', exact: true }).click();
    const newlyCreated = (await mutation(unknownReceipt)).data;
    expect(newlyCreated).toMatchObject({ created_request: true, created_equipment: true, request: { serial_number: unknownSerial, status: 'new', model: 'Modèle fictif vérifié sur l’étiquette', client: { id: company.id } } });
    expect((await api(page, `requests/${newlyCreated.request.id}/`)).assigned_technician).toBeNull();
    expect(oldApiCalls).toEqual([]);
    expect(await courier.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)).toBe(false);
    await expectCourierContrast(courier, 'Réception livreur mobile');
  } finally {
    await context.close();
  }
});

test('un enlèvement demandé par le client reste sans arrivée SAV jusqu’à la collecte puis la réception physique du livreur affecté', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('enlevement-fictif');
  const company = await owner(page, tag);
  const unit = await equipment(page, company, `COLLECTE-000021-${tag}`);
  const customerAccount = await clientAccount(page, company, tag);
  const courierA = await courierAccount(page, `${tag}-A`);
  const courierB = await courierAccount(page, `${tag}-B`);
  const customerContext = await browser.newContext();
  const courierContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const otherContext = await browser.newContext();
  const foreignContext = await browser.newContext();
  const customer = await customerContext.newPage();
  const courier = await courierContext.newPage();
  const otherCourier = await otherContext.newPage();
  const foreignCustomer = await foreignContext.newPage();
  try {
    await login(customer, customerAccount.username);
    await navigate(customer, 'Mes enlèvements');
    await expect(customer.getByRole('heading', { name: 'Mes enlèvements', exact: true })).toBeVisible();
    await customer.getByRole('button', { name: 'Demander un enlèvement', exact: true }).first().click();
    const dialog = customer.getByRole('dialog', { name: 'Demander un enlèvement', exact: true });
    const ownUnits = dialog.getByRole('combobox', { name: 'Équipement à envoyer', exact: true });
    await expect(ownUnits.locator('option')).toHaveCount(2);
    await ownUnits.selectOption(String(unit.id));
    await dialog.getByRole('textbox', { name: 'Votre n° d’appel client', exact: true }).fill(`000-COLLECTE-${tag}`);
    await dialog.getByRole('textbox', { name: 'Problème signalé', exact: true }).fill('Essai fictif de collecte : défaut déclaré avant l’arrivée atelier.');
    await dialog.getByRole('textbox', { name: 'Adresse d’enlèvement', exact: true }).fill('42 voie du laboratoire fictif, Cotonou');
    await dialog.getByRole('textbox', { name: 'Contact pour l’enlèvement', exact: true }).fill('Responsable fictif de collecte');
    await dialog.getByRole('textbox', { name: 'Téléphone du contact', exact: true }).fill('0000000042');
    const requested = mutationResponse(customer, 'logistics/pickups/');
    await dialog.getByRole('button', { name: 'Enregistrer la demande d’enlèvement', exact: true }).click();
    const pickup = (await mutation(requested)).data;
    expect(pickup).toMatchObject({ status: 'requested', equipment: unit.id, serial_number: unit.serial_number, client: { id: company.id }, client_reference: `000-COLLECTE-${tag}`, collected_at: null, received_at: null, service_request: null });
    expect(pickup.call_number || '').toBe('');
    expect(await api(page, `requests/?q=${encodeURIComponent(unit.serial_number)}`)).toEqual([]);
    await expect(customer.locator('.pickup-card').filter({ hasText: unit.serial_number })).toContainText('Pas encore réceptionné');
    expect((await response(customer, `logistics/pickups/${pickup.id}/assign/`, 'POST', { courier: courierA.id })).status()).toBe(403);

    await navigate(page, 'Logistique');
    await expect(page.getByRole('heading', { name: 'Logistique', exact: true })).toBeVisible();
    const row = page.locator('.logistics-pickups-table tbody tr').filter({ hasText: unit.serial_number });
    await expect(row).toHaveCount(1);
    await row.getByRole('combobox', { name: `Livreur pour l’enlèvement ${pickup.id}`, exact: true }).selectOption(String(courierA.id));
    const assignedResponse = mutationResponse(page, `logistics/pickups/${pickup.id}/assign/`);
    await row.getByRole('button', { name: 'Enregistrer l’affectation', exact: true }).click();
    expect((await mutation(assignedResponse)).data).toMatchObject({ id: pickup.id, status: 'assigned', assigned_courier: courierA.id });

    await login(otherCourier, courierB.username, true);
    expect((await api(otherCourier, 'logistics/pickups/')).some(item => item.id === pickup.id)).toBe(false);
    expect((await response(otherCourier, `logistics/pickups/${pickup.id}/`)).status()).toBe(404);
    await login(foreignCustomer, 'client');
    expect((await response(foreignCustomer, `logistics/pickups/${pickup.id}/`)).status()).toBe(404);

    await login(courier, courierA.username, true);
    await courierNavigate(courier, 'Tournées');
    const job = courier.locator('.courier-job-card').filter({ hasText: unit.serial_number });
    await expect(job).toHaveCount(1);
    await expect(job).toContainText('42 voie du laboratoire fictif, Cotonou');
    await expect(job).toContainText('Responsable fictif de collecte');
    const collectedResponse = mutationResponse(courier, `logistics/pickups/${pickup.id}/collect/`);
    const beforeCollect = Date.now();
    await job.getByRole('button', { name: 'Prendre en charge l’enlèvement', exact: true }).click();
    const collected = (await mutation(collectedResponse)).data;
    expect(collected).toMatchObject({ status: 'collected', received_at: null, service_request: null });
    assertServerTimestamp(collected.collected_at, beforeCollect);
    expect(await api(page, `requests/?q=${encodeURIComponent(unit.serial_number)}`)).toEqual([]);
    await expectCourierContrast(courier, 'Tournée livreur mobile');
    expect(await courier.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)).toBe(false);

    const lookupResponse = mutationResponse(courier, 'logistics/lookup/');
    await job.getByRole('button', { name: 'Réceptionner à l’atelier', exact: true }).click();
    expect((await mutation(lookupResponse)).data.equipment.id).toBe(unit.id);
    const reception = physicalReception(courier);
    await expect(reception.getByRole('textbox', { name: 'Numéro de série à réceptionner', exact: true })).toHaveValue(unit.serial_number);
    const physical = reception.getByRole('checkbox', { name: 'Je confirme avoir reçu physiquement cet onduleur.', exact: true });
    await expect(physical).not.toBeChecked();
    await expect(reception.getByRole('button', { name: 'Confirmer la réception', exact: true })).toBeDisabled();
    await physical.check();
    const receivedResponse = mutationResponse(courier, 'logistics/receive/');
    const beforeReceive = Date.now();
    await reception.getByRole('button', { name: 'Confirmer la réception', exact: true }).click();
    const received = await mutation(receivedResponse);
    expect(received.result.request().postDataJSON().pickup).toBe(pickup.id);
    expect(received.data).toMatchObject({ created_request: true, created_equipment: false, request: { status: 'new', serial_number: unit.serial_number, client_reference: `000-COLLECTE-${tag}` } });
    assertServerTimestamp(received.data.request.arrived_at, beforeReceive);
    const savedPickup = await api(page, `logistics/pickups/${pickup.id}/`);
    expect(savedPickup).toMatchObject({ status: 'received', service_request: received.data.request.id, call_number: received.data.request.call_number });
    assertServerTimestamp(savedPickup.received_at, beforeReceive);
    const request = await api(page, `requests/${received.data.request.id}/`);
    expect(request).toMatchObject({ equipment: unit.id, status: 'new', assigned_technician: null });
    expect(Date.parse(request.arrived_at)).toBe(Date.parse(received.data.request.arrived_at));
    expect(await api(page, `requests/?q=${encodeURIComponent(unit.serial_number)}`)).toHaveLength(1);
    const ownPickup = await api(customer, `logistics/pickups/${pickup.id}/`);
    expect(ownPickup.service_request).toBe(request.id);
    expect(JSON.stringify(ownPickup)).not.toContain(company.notes);
    expect(JSON.stringify(ownPickup)).not.toContain(company.tax_id);
  } finally {
    await Promise.all([customerContext.close(), courierContext.close(), otherContext.close(), foreignContext.close()]);
  }
});

test('les transports affectés livrent le remplacement validé ou retournent l’original avec une remise horodatée indépendante de la clôture et de la finance', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('remise-fictive');
  const company = await owner(page, tag);
  const courierAccountA = await courierAccount(page, `${tag}-A`);
  const courierAccountB = await courierAccount(page, `${tag}-B`);
  const customerAccount = await clientAccount(page, company, tag);
  const original = await equipment(page, company, `ORIGINE-000061-${tag}`);
  const exchange = await api(page, 'requests/', 'POST', { equipment: original.id, subject: `Échange logistique fictif ${tag}`, client_reference: `000-CLIENT-${tag}`, status: 'exchange' });
  const replacementSerial = `REMPLACEMENT-000062-${tag}`;
  await api(page, `requests/${exchange.id}/exchange/`, 'PATCH', { replacement_serial_number: replacementSerial, replacement_model: 'Remplacement fictif à livrer', replacement_brand: 'Eaton' });
  const validated = await api(page, `requests/${exchange.id}/exchange/validate/`, 'POST', { mark_ready: true });
  expect(validated).toMatchObject({ status: 'ready_for_delivery', exchange: { is_ready: true, is_validated: true, is_invoiced: false } });
  const returnUnit = await equipment(page, company, `RETOUR-000063-${tag}`);
  const returnRequest = await api(page, 'requests/', 'POST', { equipment: returnUnit.id, subject: `Retour logistique fictif ${tag}`, client_reference: `000-RETOUR-${tag}`, status: 'testing' });
  const classified = await api(page, `requests/${returnRequest.id}/disposition/nonrepairable/`, 'POST', { diagnosis: 'Diagnostic fictif : matériel non réparable, retour au propriétaire.', fee_mode: 'billable' });
  expect(classified).toMatchObject({ status: 'return_to_client', disposition: { outcome: 'nonrepairable', finance_validated_at: null } });

  await navigate(page, 'Logistique');
  await page.getByRole('group', { name: 'Files logistiques', exact: true }).getByRole('button', { name: /^Livraisons et retours à affecter/ }).click();
  const jobs = [];
  for (const record of [exchange, returnRequest]) {
    const row = page.locator('.logistics-candidates-table tbody tr').filter({ hasText: record.call_number || record.reference });
    await expect(row).toHaveCount(1);
    await row.getByRole('combobox', { name: `Livreur pour le dossier ${record.call_number || record.reference}`, exact: true }).selectOption(String(courierAccountA.id));
    await row.getByRole('textbox', { name: 'Adresse de livraison', exact: true }).fill('61 voie du laboratoire de remise fictif, Cotonou');
    await row.getByRole('textbox', { name: 'Contact de livraison', exact: true }).fill('Contact fictif pour la remise');
    await row.getByRole('textbox', { name: 'Téléphone de livraison', exact: true }).fill('0000000061');
    const assigned = mutationResponse(page, 'logistics/outbound/');
    await row.getByRole('button', { name: 'Affecter le transport', exact: true }).click();
    jobs.push((await mutation(assigned)).data);
  }
  const [delivery, returned] = jobs;
  expect(delivery).toMatchObject({ kind: 'delivery', status: 'assigned', service_request: exchange.id, equipment: validated.exchange.replacement_equipment, serial_number: replacementSerial, assigned_courier: courierAccountA.id, delivery_address: '61 voie du laboratoire de remise fictif, Cotonou' });
  expect(delivery.equipment).not.toBe(original.id);
  expect(delivery.serial_number).not.toBe(original.serial_number);
  expect(returned).toMatchObject({ kind: 'return', status: 'assigned', service_request: returnRequest.id, equipment: returnUnit.id, serial_number: returnUnit.serial_number, assigned_courier: courierAccountA.id });

  const courierContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const otherContext = await browser.newContext();
  const clientContext = await browser.newContext();
  const foreignContext = await browser.newContext();
  const courier = await courierContext.newPage();
  const otherCourier = await otherContext.newPage();
  const customer = await clientContext.newPage();
  const foreignCustomer = await foreignContext.newPage();
  try {
    await login(otherCourier, courierAccountB.username, true);
    expect((await api(otherCourier, 'logistics/outbound/')).some(job => jobs.some(own => own.id === job.id))).toBe(false);
    expect((await response(otherCourier, `logistics/outbound/${delivery.id}/`)).status()).toBe(404);
    await login(courier, courierAccountA.username, true);
    const completed = [];
    for (const [index, job] of jobs.entries()) {
      await courierNavigate(courier, index === 0 ? 'Prêts' : 'Retours');
      const card = courier.locator('.courier-job-card').filter({ hasText: job.serial_number });
      await expect(card).toHaveCount(1);
      await expect(card).toContainText('61 voie du laboratoire de remise fictif, Cotonou');
      await expectCourierContrast(courier, index === 0 ? 'Livraison livreur mobile' : 'Retour livreur mobile');
      expect(await courier.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)).toBe(false);
      await card.getByRole('button', { name: `Confirmer la remise ${job.call_number}`, exact: true }).click();
      const dialog = courier.getByRole('dialog', { name: 'Confirmer la remise au client', exact: true });
      const recipient = `Destinataire fictif ${index + 1}`;
      await dialog.getByRole('textbox', { name: 'Nom du destinataire', exact: true }).fill(recipient);
      const save = dialog.getByRole('button', { name: 'Enregistrer la remise', exact: true });
      await expect(save).toBeDisabled();
      await dialog.getByRole('checkbox', { name: 'Je confirme avoir remis physiquement cet onduleur au destinataire indiqué.', exact: true }).check();
      const proofResponse = mutationResponse(courier, `logistics/outbound/${job.id}/handoff/`);
      const before = Date.now();
      await save.click();
      const proof = (await mutation(proofResponse)).data;
      expect(proof).toMatchObject({ id: job.id, status: 'completed', serial_number: job.serial_number, recipient_name: recipient, handed_over_by_role: 'courier' });
      assertServerTimestamp(proof.handed_over_at, before);
      expect(proof.handed_over_by_name).toBeTruthy();
      await expect(dialog.locator('.handoff-receipt')).toContainText('Remise enregistrée par le livreur');
      await expect(dialog.locator('.handoff-receipt')).toContainText(recipient);
      await expect(dialog.locator('.handoff-receipt')).toContainText('Aucune signature électronique du client n’a été recueillie.');
      await expectCourierContrast(courier, 'Preuve de remise sur téléphone');
      await dialog.getByRole('button', { name: 'Fermer', exact: true }).last().click();
      const replay = await api(courier, `logistics/outbound/${job.id}/handoff/`, 'POST', { recipient_name: recipient });
      expect(Date.parse(replay.handed_over_at)).toBe(Date.parse(proof.handed_over_at));
      expect((await response(courier, `logistics/outbound/${job.id}/handoff/`, 'POST', { recipient_name: 'Un autre destinataire fictif' })).status()).toBe(400);
      completed.push(proof);
    }
    expect(await api(page, `requests/${exchange.id}/`)).toMatchObject({ status: 'ready_for_delivery', closed_at: null, exchange: { is_invoiced: false } });
    expect(await api(page, `requests/${returnRequest.id}/`)).toMatchObject({ status: 'return_to_client', closed_at: null, disposition: { finance_validated_at: null, state: 'awaiting_quote' } });
    await login(customer, customerAccount.username);
    await navigate(customer, 'Mes enlèvements');
    await customer.getByRole('group', { name: 'Suivi de mes transports', exact: true }).getByRole('button', { name: /^Livraisons et retours/ }).click();
    for (const proof of completed) {
      const card = customer.locator('.pickup-card').filter({ hasText: proof.serial_number });
      await expect(card).toContainText(proof.recipient_name);
      await expect(card).toContainText('Remise enregistrée par le livreur');
    }
    const owned = await api(customer, 'logistics/outbound/');
    expect(owned.map(job => job.id).sort()).toEqual(jobs.map(job => job.id).sort());
    expect(JSON.stringify(owned)).not.toContain(company.notes);
    expect(JSON.stringify(owned)).not.toContain(company.tax_id);
    await login(foreignCustomer, 'client');
    for (const job of jobs) expect((await response(foreignCustomer, `logistics/outbound/${job.id}/`)).status()).toBe(404);
  } finally {
    await Promise.all([courierContext.close(), otherContext.close(), clientContext.close(), foreignContext.close()]);
  }
});

test('les photos réelles proposent les numéros sans réception automatique et une caméra simulée ignore le code article EAN', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('lecture-fictive');
  const account = await courierAccount(page, tag);
  const photoNumbers = ['TVM-BAR-00042', 'TVM-OCR-00042', 'TVM-BAR-00043'];
  const beforePhotos = new Map();
  for (const number of photoNumbers) beforePhotos.set(number, {
    equipment: await api(page, `equipment/?serial=${encodeURIComponent(number)}`),
    requests: await api(page, `requests/?q=${encodeURIComponent(number)}`),
  });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  // This camera double verifies browser capture/format filtering and cleanup.
  // It does not assert that a physical phone camera has been tested.
  await context.addInitScript(() => {
    window.__captureCspViolations = [];
    window.addEventListener('securitypolicyviolation', event => window.__captureCspViolations.push({ directive: event.effectiveDirective, blocked: event.blockedURI }));
    window.__cameraDetectCount = 0;
    window.__cameraFormats = [];
    window.__nextCameraSerial = '';
    class SimulatedBarcodeDetector {
      static async getSupportedFormats() { return ['code_128', 'ean_13']; }
      constructor(options) { window.__cameraFormats = options.formats; }
      async detect() {
        window.__cameraDetectCount += 1;
        return window.__nextCameraSerial
          ? [{ rawValue: window.__nextCameraSerial, format: 'code_128' }]
          : [{ rawValue: '5901234123457', format: 'ean_13' }];
      }
    }
    Object.defineProperty(window, 'BarcodeDetector', { configurable: true, value: SimulatedBarcodeDetector });
    const mediaDevices = navigator.mediaDevices || {};
    if (!navigator.mediaDevices) Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: mediaDevices });
    Object.defineProperty(mediaDevices, 'getUserMedia', { configurable: true, value: async () => {
      const canvas = document.createElement('canvas');
      canvas.width = 320;
      canvas.height = 240;
      const drawing = canvas.getContext('2d');
      const draw = () => { drawing.fillStyle = '#dae6f5'; drawing.fillRect(0, 0, 320, 240); };
      draw();
      const stream = canvas.captureStream(10);
      const repaint = setInterval(draw, 100);
      stream.getTracks().forEach(track => {
        const stop = track.stop.bind(track);
        track.stop = () => { clearInterval(repaint); stop(); };
      });
      window.__cameraStream = stream;
      return stream;
    } });
  });
  const courier = await context.newPage();
  const errors = [];
  const lookups = [];
  const receptions = [];
  courier.on('console', message => { if (message.type() === 'error' && /content.security.policy|violates.*directive|refused to load.*blob/i.test(message.text())) errors.push(message.text()); });
  courier.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (path === '/api/logistics/lookup/' && request.method() === 'POST') lookups.push(request);
    if (path === '/api/logistics/receive/' && request.method() === 'POST') receptions.push(request);
  });
  try {
    await login(courier, account.username, true);
    await courierNavigate(courier, 'Réception');
    const reception = physicalReception(courier);
    const serial = reception.getByRole('textbox', { name: 'Numéro de série à réceptionner', exact: true });
    const initial = `SAISIE-CONSERVEE-000077-${tag}`;
    await serial.fill(initial);
    await reception.getByRole('button', { name: 'Scanner avec la caméra', exact: true }).click();
    await expect.poll(() => courier.evaluate(() => window.__cameraDetectCount)).toBeGreaterThanOrEqual(2);
    expect(await courier.evaluate(() => window.__cameraFormats)).toEqual(['code_128']);
    await expect(serial).toHaveValue(initial);
    expect(lookups).toHaveLength(0);
    expect(receptions).toHaveLength(0);
    const cameraSerial = `CAMERA-FICTIVE-000078-${tag}`;
    const cameraLookup = mutationResponse(courier, 'logistics/lookup/');
    await courier.evaluate(value => { window.__nextCameraSerial = value; }, cameraSerial);
    await mutation(cameraLookup);
    await expect(serial).toHaveValue(cameraSerial);
    await expect.poll(() => courier.evaluate(() => window.__cameraStream.getTracks().every(track => track.readyState === 'ended'))).toBe(true);
    await expect(reception.getByRole('button', { name: 'Scanner avec la caméra', exact: true })).toBeVisible();
    expect(receptions).toHaveLength(0);

    await reception.getByRole('button', { name: 'Lire une photo', exact: true }).click();
    const cases = [
      { file: 'serial_barcode_fictif.png', method: 'barcode', status: 'recognized', candidates: ['TVM-BAR-00042'], selected: 'TVM-BAR-00042' },
      { file: 'serial_ocr_fictif.png', method: 'ocr', status: 'recognized', candidates: ['TVM-OCR-00042'], selected: 'TVM-OCR-00042' },
      { file: 'serial_barcodes_ambigus_fictifs.png', method: 'barcode', status: 'ambiguous', candidates: ['TVM-BAR-00042', 'TVM-BAR-00043'], selected: 'TVM-BAR-00043' },
    ];
    for (const example of cases) {
      const current = await serial.inputValue();
      const lookupCount = lookups.length;
      await reception.getByLabel('Photo de l’étiquette', { exact: true }).setInputFiles(fixturePath(example.file));
      const preview = reception.locator('.serial-capture-photo-preview');
      await expect(preview).toBeVisible();
      await expect.poll(() => preview.evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true);
      const recognizedResponse = mutationResponse(courier, 'logistics/recognize-serial/');
      await reception.getByRole('button', { name: 'Lire l’étiquette photo', exact: true }).click();
      const recognized = (await mutation(recognizedResponse)).data;
      expect(recognized).toMatchObject({ method: example.method, status: example.status });
      expect(recognized.candidates.map(candidate => candidate.serial_number).sort()).toEqual([...example.candidates].sort());
      const choices = reception.getByRole('group', { name: 'Numéros de série proposés', exact: true });
      await expect(choices).toBeVisible();
      for (const candidate of example.candidates) await expect(choices.getByRole('button', { name: `Utiliser le numéro ${candidate}`, exact: true })).toBeVisible();
      await expect(serial).toHaveValue(current);
      expect(lookups).toHaveLength(lookupCount);
      expect(receptions).toHaveLength(0);
      await expectCourierContrast(courier, 'Lecture photo sur téléphone');
      expect(await courier.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)).toBe(false);
      const selectedLookup = mutationResponse(courier, 'logistics/lookup/');
      await choices.getByRole('button', { name: `Utiliser le numéro ${example.selected}`, exact: true }).click();
      await mutation(selectedLookup);
      await expect(serial).toHaveValue(example.selected);
      expect(receptions).toHaveLength(0);
    }
    // Article numbers remain possible as explicit manual text; camera support
    // must not silently mistake an EAN printed beside the serial for that serial.
    await serial.fill('5901234123457');
    await expect(serial).toHaveValue('5901234123457');
    expect(receptions).toHaveLength(0);
    for (const number of photoNumbers) {
      expect(await api(page, `requests/?q=${encodeURIComponent(number)}`)).toEqual(beforePhotos.get(number).requests);
      expect(await api(page, `equipment/?serial=${encodeURIComponent(number)}`)).toEqual(beforePhotos.get(number).equipment);
    }
    expect(await courier.evaluate(() => window.__captureCspViolations)).toEqual([]);
    expect(errors).toEqual([]);
  } finally {
    await context.close();
  }
});
