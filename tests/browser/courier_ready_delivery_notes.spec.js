import { test, expect } from '@playwright/test';
import { createHash, randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { acceptCurrentOutboundMission } from './legacy_navigation.js';

const password = process.env.TVM_DEMO_PASSWORD;
const marker = () => `BL-TEST-${Date.now()}-${Math.random().toString(36).slice(2, 7).toUpperCase()}`;
const python = fileURLToPath(new URL('../../.venv/bin/python', import.meta.url));

async function login(page, username = 'admin', courier = false) {
  if (!password) throw new Error('Utiliser bash scripts/e2e.sh avec le mot de passe local privé.');
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

function mutation(page, path) {
  return page.waitForResponse(result => new URL(result.url()).pathname === `/api/${path}` && result.request().method() === 'POST');
}

async function laboratory(page) {
  const tag = marker();
  const owner = async suffix => api(page, 'clients/', 'POST', {
    name: `Centre fictif BL ${suffix} ${tag}`, address: `${suffix} voie de laboratoire fictive`,
    contact_name: `Contact fictif ${suffix}`, notes: `NOTE-CLIENT-PRIVEE-${suffix}-${tag}`,
  });
  const companyA = await owner('A'), companyB = await owner('B');
  const driver = suffix => api(page, 'users/', 'POST', {
    username: `bl-driver-${suffix}-${tag}`, first_name: `Livreur fictif ${suffix}`, role: 'courier', password,
  });
  const driverA = await driver('A'), driverB = await driver('B');
  const external = await api(page, 'users/', 'POST', {
    username: `bl-external-${tag}`, first_name: 'Livreur client fictif', role: 'courier',
    courier_kind: 'client', client: companyA.id, password,
  });
  return { tag, companyA, companyB, driverA, driverB, external };
}

async function repaired(page, lab, company, suffix) {
  const unit = await api(page, 'equipment/', 'POST', {
    client: company.id, serial_number: `${lab.tag}-${suffix}`, model: `Modèle fictif ${suffix}`, brand: 'Eaton',
  });
  const record = await api(page, 'requests/', 'POST', {
    equipment: unit.id, subject: `Essais BL fictifs ${lab.tag} ${suffix}`, status: 'testing',
    client_reference: `000-CENTRE-${suffix}-${lab.tag}`, description: `DESCRIPTION-PRIVEE-${suffix}-${lab.tag}`,
  });
  const { as_of: today } = await api(page, 'requests/categories/');
  const ready = await api(page, `requests/${record.id}/disposition/repair/`, 'POST', {
    diagnosis: 'Essais fictifs de réparation réussis au laboratoire.', tests_passed: true, tested_on: today,
  });
  expect(ready.status).toBe('ready_for_delivery');
  return { unit, record: ready };
}

async function exchanged(page, lab, company, suffix) {
  const original = await api(page, 'equipment/', 'POST', {
    client: company.id, serial_number: `${lab.tag}-${suffix}-ANCIEN`, model: 'Ancien modèle fictif',
  });
  const record = await api(page, 'requests/', 'POST', {
    equipment: original.id, subject: `Échange BL fictif ${lab.tag}`, status: 'exchange', client_reference: `000-ECHANGE-${lab.tag}`,
  });
  const serial = `${lab.tag}-${suffix}-NOUVEAU`;
  await api(page, `requests/${record.id}/exchange/`, 'PATCH', {
    replacement_serial_number: serial, replacement_model: 'Remplacement fictif BL', replacement_brand: 'Eaton',
  });
  let ready = await api(page, `requests/${record.id}/exchange/validate/`, 'POST', { mark_ready: true });
  const { as_of: today } = await api(page, 'requests/categories/');
  const invoiceReference = `FACTURE-INTERNE-${lab.tag}`;
  const financeNote = `FINANCE-PRIVEE-${lab.tag}`;
  ready = await api(page, `requests/${record.id}/exchange/billing/`, 'POST', {
    invoice_reference: invoiceReference, invoiced_on: today, billing_notes: financeNote,
  });
  return { original, unit: { id: ready.exchange.replacement_equipment, serial_number: serial }, record: ready, invoiceReference, financeNote };
}

async function openReady(page, tag = '') {
  await page.getByRole('navigation', { name: 'Navigation livreur', exact: true }).getByRole('button', { name: 'Prêts', exact: true }).click();
  await page.getByRole('button', { name: 'File partagée', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'File partagée des prêts à livrer', exact: true })).toBeVisible();
  await page.getByLabel('Rechercher dans les prêts à livrer', { exact: true }).fill(tag);
}

function readyCard(page, fixture) {
  return page.locator('.courier-ready-card').filter({ hasText: fixture.unit.serial_number });
}

async function claimViaUI(page, fixture) {
  const card = readyCard(page, fixture);
  await card.getByRole('button', { name: 'Prendre la livraison', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Prendre la livraison', exact: true });
  await expect(dialog).toContainText(fixture.record.reference);
  const saved = mutation(page, `logistics/ready-queue/${fixture.record.id}/claim/`);
  await dialog.getByRole('button', { name: 'Oui', exact: true }).click();
  const result = await saved;
  expect(result.status(), await result.text()).toBe(200);
  const job = await result.json();
  expect(job).toMatchObject({ accepted: true, handed_over_at: null, service_request: fixture.record.id });
  expect(job.accepted_revision).toBe(job.assignment_revision);
  await expect(dialog).toHaveCount(0);
  return job;
}

async function claimViaAPI(page, fixture) {
  const rows = await api(page, `logistics/ready-queue/?q=${encodeURIComponent(fixture.unit.serial_number)}`);
  const row = rows.find(item => item.id === fixture.record.id);
  expect(row.can_claim).toBe(true);
  return api(page, `logistics/ready-queue/${fixture.record.id}/claim/`, 'POST', { expected_revision: row.expected_revision });
}

function pdfText(buffer) {
  return execFileSync(python, ['-c', 'import io,sys\nfrom pypdf import PdfReader\nr=PdfReader(io.BytesIO(sys.stdin.buffer.read()))\nprint("\\n".join(p.extract_text() or "" for p in r.pages))'], {
    input: buffer, timeout: 10000, maxBuffer: 1024 * 1024,
  }).toString('utf8');
}

test('la file TVM réunit les clients et réserve une livraison acceptée sans vol de mission ni double réservation concurrente', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const lab = await laboratory(page);
  const first = await repaired(page, lab, lab.companyA, 'PRET-A');
  const second = await repaired(page, lab, lab.companyB, 'PRET-B');
  const concurrent = await repaired(page, lab, lab.companyA, 'COURSE');
  const contextA = await browser.newContext(), contextB = await browser.newContext();
  const driverA = await contextA.newPage(), driverB = await contextB.newPage();
  try {
    await login(driverA, lab.driverA.username, true);
    await login(driverB, lab.driverB.username, true);
    const notifications = await api(driverA, 'logistics/notifications/');
    const notice = notifications.results.filter(item => item.event === 'ready_availability' && item.service_request === first.record.id);
    expect(notice).toHaveLength(1);
    expect(notice[0]).toMatchObject({ channel: 'in_app', target: 'courier_ready_queue', details: { available: true } });
    expect(notice[0].details.request).toMatchObject({ serial_number: first.unit.serial_number, client: { id: lab.companyA.id } });
    expect(JSON.stringify(notifications)).not.toContain(lab.companyA.notes);
    await openReady(driverA, lab.tag);
    await expect(driverA.locator('.courier-ready-card')).toHaveCount(3);
    await expect(readyCard(driverA, first)).toContainText(lab.companyA.name);
    await expect(readyCard(driverA, second)).toContainText(lab.companyB.name);
    await expect(readyCard(driverA, first)).toContainText('Disponible');
    await readyCard(driverA, first).getByRole('button', { name: 'Prendre la livraison', exact: true }).click();
    const cancelled = driverA.getByRole('dialog', { name: 'Prendre la livraison', exact: true });
    await cancelled.getByRole('button', { name: 'Annuler', exact: true }).click();
    expect((await api(page, 'logistics/outbound/')).some(job => job.service_request === first.record.id)).toBe(false);
    const ownedA = await claimViaUI(driverA, first);
    expect(ownedA.assigned_courier).toBe(lab.driverA.id);
    await openReady(driverB, lab.tag);
    const reserved = readyCard(driverB, first);
    await expect(reserved).toContainText('Affecté');
    await expect(reserved).toContainText('Mission acceptée');
    await expect(reserved.getByRole('button', { name: 'Prendre la livraison', exact: true })).toHaveCount(0);
    const stolen = await response(driverB, `logistics/ready-queue/${first.record.id}/claim/`, 'POST', { expected_revision: ownedA.assignment_revision });
    expect(stolen.status()).toBe(409);
    const ownedB = await claimViaUI(driverB, second);
    expect(ownedB.assigned_courier).toBe(lab.driverB.id);
    const rows = await api(driverA, `logistics/ready-queue/?q=${encodeURIComponent(concurrent.unit.serial_number)}`);
    const revision = rows.find(row => row.id === concurrent.record.id).expected_revision;
    const races = await Promise.all([driverA, driverB].map(actor => response(actor,
      `logistics/ready-queue/${concurrent.record.id}/claim/`, 'POST', { expected_revision: revision })));
    expect(races.map(result => result.status()).sort()).toEqual([200, 409]);
    const jobs = (await api(page, 'logistics/outbound/')).filter(job => job.service_request === concurrent.record.id);
    expect(jobs).toHaveLength(1);
    expect(jobs[0].accepted).toBe(true);
    for (const fixture of [first, second, concurrent]) {
      const record = await api(page, `requests/${fixture.record.id}/`);
      expect(record).toMatchObject({ status: 'ready_for_delivery', closed_at: null });
    }
    expect((await api(driverA, 'logistics/outbound/')).every(job => job.handed_over_at === null)).toBe(true);
    expect((await api(driverB, 'logistics/outbound/')).every(job => job.handed_over_at === null)).toBe(true);
    expect((await driverA.request.get('/api/requests/')).status()).toBe(403);
  } finally { await Promise.all([contextA.close(), contextB.close()]); }
});

test('une affectation administrative attend l’acceptation du livreur désigné et les livreurs clients restent dans leur propre périmètre', async ({ page, browser }) => {
  await login(page);
  const lab = await laboratory(page);
  const fixture = await repaired(page, lab, lab.companyB, 'AFFECTE');
  const externalFixture = await repaired(page, lab, lab.companyA, 'CLIENT');
  const job = await api(page, 'logistics/outbound/', 'POST', { service_request: fixture.record.id, courier: lab.driverB.id });
  const externalJob = await api(page, 'logistics/outbound/', 'POST', { service_request: externalFixture.record.id, courier: lab.external.id });
  expect(job).toMatchObject({ accepted: false, accepted_at: null, can_handoff: true });
  const contextA = await browser.newContext(), contextB = await browser.newContext(), externalContext = await browser.newContext();
  const driverA = await contextA.newPage(), driverB = await contextB.newPage(), external = await externalContext.newPage();
  try {
    await login(driverA, lab.driverA.username, true);
    await login(driverB, lab.driverB.username, true);
    const assignedNotices = await api(driverB, 'logistics/notifications/');
    const assignedNotice = assignedNotices.results.filter(item => item.event === 'outbound_assignment' && item.service_request === fixture.record.id);
    expect(assignedNotice).toHaveLength(1);
    expect(assignedNotice[0]).toMatchObject({ channel: 'in_app', target: 'courier_missions',
      details: { available: true, job: { id: job.id, accepted: false, assignment_revision: job.assignment_revision } } });
    expect((await response(driverA, `logistics/outbound/${job.id}/accept/`, 'POST', { expected_revision: job.assignment_revision, accept: true })).status()).toBe(404);
    expect((await response(driverB, `logistics/outbound/${job.id}/handoff/`, 'POST', { recipient_name: 'Destinataire fictif avant acceptation' })).status()).toBe(403);
    await openReady(driverB, lab.tag);
    const card = readyCard(driverB, fixture);
    await expect(card).toContainText('Acceptation à confirmer');
    await card.getByRole('button', { name: 'Accepter la mission', exact: true }).click();
    const cancelled = driverB.getByRole('dialog', { name: 'Accepter la mission', exact: true });
    await cancelled.getByRole('button', { name: 'Annuler', exact: true }).click();
    expect((await api(page, `logistics/outbound/${job.id}/`)).accepted).toBe(false);
    const accepted = await acceptCurrentOutboundMission(driverB, card, job);
    expect(accepted).toMatchObject({ accepted: true, handed_over_at: null, assigned_courier: lab.driverB.id });
    expect(accepted.accepted_by).toBe(lab.driverB.id);
    expect((await api(page, `requests/${fixture.record.id}/`))).toMatchObject({ status: 'ready_for_delivery', closed_at: null });

    await login(external, lab.external.username, true);
    expect((await response(external, 'logistics/ready-queue/')).status()).toBe(403);
    expect((await response(external, `logistics/ready-queue/${fixture.record.id}/claim/`, 'POST', { expected_revision: 0 })).status()).toBe(403);
    expect((await api(external, 'logistics/outbound/')).map(item => item.id)).toEqual([externalJob.id]);
    expect((await response(external, `logistics/outbound/${job.id}/`)).status()).toBe(404);
    const externalNotices = await api(external, 'logistics/notifications/');
    expect(externalNotices.results.some(item => item.event === 'ready_availability')).toBe(false);
    expect(JSON.stringify(externalNotices)).not.toContain(lab.companyB.name);
    await expect(external.getByRole('button', { name: 'File partagée', exact: true })).toHaveCount(0);
    expect((await api(page, `logistics/outbound/${externalJob.id}/`)).handed_over_at).toBeNull();
  } finally { await Promise.all([contextA.close(), contextB.close(), externalContext.close()]); }
});

test('les BL individuel et par lot conservent leurs PDF sans mélange de clients, remise automatique ou clôture du SAV', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const lab = await laboratory(page);
  const first = await repaired(page, lab, lab.companyA, 'LOT-A1');
  const exchange = await exchanged(page, lab, lab.companyA, 'LOT-A2');
  const other = await repaired(page, lab, lab.companyB, 'INDIVIDUEL');
  const context = await browser.newContext(), foreignContext = await browser.newContext();
  const driver = await context.newPage(), foreignDriver = await foreignContext.newPage();
  try {
    await login(driver, lab.driverA.username, true);
    await login(foreignDriver, lab.driverB.username, true);
    const jobs = [];
    for (const fixture of [first, exchange, other]) jobs.push(await claimViaAPI(driver, fixture));
    const [jobA1, jobA2, jobB] = jobs;
    const mixed = await response(driver, 'logistics/delivery-notes/', 'POST', {
      request_key: randomUUID(), job_ids: [jobA1.id, jobB.id],
    });
    expect(mixed.status()).toBe(400);
    expect(await api(driver, 'logistics/delivery-notes/')).toEqual([]);
    await driver.reload();
    await driver.getByRole('navigation', { name: 'Navigation livreur', exact: true }).getByRole('button', { name: 'Prêts', exact: true }).click();
    await driver.getByRole('button', { name: 'Bons de livraison', exact: true }).click();
    for (const job of [jobA1, jobA2]) {
      await driver.getByRole('checkbox', { name: `Sélectionner ${job.call_number} · ${job.serial_number}`, exact: true }).check();
    }
    await expect(driver.getByRole('checkbox', { name: `Sélectionner ${jobB.call_number} · ${jobB.serial_number}`, exact: true })).toBeDisabled();
    await driver.getByRole('button', { name: 'Générer le BL du lot (2)', exact: true }).click();
    const preview = driver.getByRole('dialog', { name: 'Vérifier le bon de livraison', exact: true });
    await expect(preview).toContainText(lab.companyA.name);
    await expect(preview).toContainText(jobA1.serial_number);
    await expect(preview).toContainText(jobA2.serial_number);
    const comment = `Commentaire public fictif du lot ${lab.tag}`;
    await preview.getByLabel('Commentaire du BL (facultatif, visible sur le PDF)', { exact: true }).fill(comment);
    const creating = mutation(driver, 'logistics/delivery-notes/');
    await preview.getByRole('button', { name: 'Créer le bon de livraison', exact: true }).click();
    const creation = await creating;
    expect(creation.status(), await creation.text()).toBe(201);
    const note = await creation.json();
    expect(note).toMatchObject({ status: 'prepared', line_count: 2, client: { id: lab.companyA.id }, courier: { id: lab.driverA.id } });
    for (const hidden of [lab.companyA.notes, exchange.financeNote, exchange.invoiceReference]) expect(JSON.stringify(note)).not.toContain(hidden);
    const prepared = driver.getByRole('dialog', { name: 'Bon de livraison préparé', exact: true });
    const download = prepared.getByRole('link', { name: 'Télécharger le BL PDF', exact: true });
    await expect(download).toHaveAttribute('href', note.pdf_url);
    const pdfResponse = await driver.request.get(note.pdf_url);
    expect(pdfResponse.status()).toBe(200);
    expect(pdfResponse.headers()['content-type']).toContain('application/pdf');
    expect(pdfResponse.headers()['cache-control']).toContain('private');
    expect(pdfResponse.headers()['content-disposition']).toMatch(/^attachment;/);
    expect(pdfResponse.headers()['x-content-type-options']).toBe('nosniff');
    const pdf = await pdfResponse.body();
    expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
    expect(createHash('sha256').update(pdf).digest('hex')).toBe(note.pdf_sha256);
    const text = pdfText(pdf);
    // PDF layout may wrap a long serial or reference onto another line.
    const denseText = text.replace(/\s+/g, '');
    for (const expected of [note.reference, lab.companyA.name, jobA1.serial_number, jobA2.serial_number, exchange.original.serial_number, jobA1.call_number, jobA2.call_number, jobA1.client_reference, jobA2.client_reference, comment]) expect(denseText).toContain(expected.replace(/\s+/g, ''));
    for (const hidden of [lab.companyA.notes, exchange.financeNote, exchange.invoiceReference, first.record.description, jobB.serial_number]) expect(denseText).not.toContain(hidden.replace(/\s+/g, ''));
    expect(text).toMatch(/ne (?:confirme|vaut)|remise.*distincte|aucune remise/i);
    const replay = await response(driver, 'logistics/delivery-notes/', 'POST', creation.request().postDataJSON());
    expect(replay.status()).toBe(200);
    expect((await replay.json()).id).toBe(note.id);
    expect((await response(foreignDriver, `logistics/delivery-notes/${note.id}/`)).status()).toBe(404);
    expect((await foreignDriver.request.get(note.pdf_url)).status()).toBe(404);
    await api(page, `clients/${lab.companyA.id}/`, 'PATCH', { address: 'Nouvelle adresse fictive après préparation', notes: `NOUVELLE-NOTE-PRIVEE-${lab.tag}` });
    const reprint = await driver.request.get(note.pdf_url);
    expect((await reprint.body()).equals(pdf)).toBe(true);
    await prepared.getByRole('button', { name: 'Fermer', exact: true }).last().click();

    const individual = driver.locator('.courier-bl-job').filter({ hasText: jobB.serial_number });
    await individual.getByRole('button', { name: 'Préparer le BL', exact: true }).click();
    const singlePreview = driver.getByRole('dialog', { name: 'Vérifier le bon de livraison', exact: true });
    const singleCreating = mutation(driver, 'logistics/delivery-notes/');
    await singlePreview.getByRole('button', { name: 'Créer le bon de livraison', exact: true }).click();
    const singleResponse = await singleCreating;
    expect(singleResponse.status()).toBe(201);
    const single = await singleResponse.json();
    expect(single).toMatchObject({ line_count: 1, client: { id: lab.companyB.id } });
    expect(single.lines[0]).toMatchObject({ serial_number: jobB.serial_number, call_number: jobB.call_number });
    const individualPdfResponse = await driver.request.get(single.pdf_url);
    expect(individualPdfResponse.status()).toBe(200);
    const individualPdf = await individualPdfResponse.body();
    for (const fixture of [first, exchange, other]) {
      expect(await api(page, `requests/${fixture.record.id}/`)).toMatchObject({ status: 'ready_for_delivery', closed_at: null });
    }
    for (const job of jobs) {
      expect(await api(page, `logistics/outbound/${job.id}/`)).toMatchObject({ accepted: true, handed_over_at: null, recipient_name: '' });
    }
    // Reassigning one line invalidates the lot and releases its other line;
    // the old courier loses access while the administrator retains the audit.
    const reassigned = await api(page, `logistics/outbound/${jobA1.id}/assign/`, 'POST', {
      courier: lab.driverB.id, expected_revision: jobA1.assignment_revision,
    });
    expect(reassigned).toMatchObject({ assigned_courier: lab.driverB.id, accepted: false, handed_over_at: null });
    expect((await driver.request.get(note.pdf_url)).status()).toBe(404);
    expect((await api(page, `logistics/delivery-notes/${note.id}/`)).status).toBe('cancelled');
    expect((await (await page.request.get(note.pdf_url)).body()).equals(pdf)).toBe(true);
    const renewed = await response(driver, 'logistics/delivery-notes/', 'POST', { request_key: randomUUID(), job_ids: [jobA2.id] });
    expect(renewed.status(), await renewed.text()).toBe(201);
    expect((await renewed.json()).id).not.toBe(note.id);
    // A later, explicit physical handoff retains the original individual PDF.
    const proof = await api(driver, `logistics/outbound/${jobB.id}/handoff/`, 'POST', { recipient_name: 'Destinataire fictif après impression du BL' });
    expect(proof.handed_over_at).toBeTruthy();
    const historical = await driver.request.get(single.pdf_url);
    expect(historical.status()).toBe(200);
    expect((await historical.body()).equals(individualPdf)).toBe(true);
    expect(await api(page, `requests/${other.record.id}/`)).toMatchObject({ status: 'ready_for_delivery', closed_at: null });
  } finally { await Promise.all([context.close(), foreignContext.close()]); }
});
