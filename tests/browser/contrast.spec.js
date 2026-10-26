import { test, expect } from '@playwright/test';

const password = process.env.TVM_DEMO_PASSWORD;

async function login(page, username) {
  if (!password) throw new Error('TVM_DEMO_PASSWORD requis ; utiliser bash scripts/e2e.sh.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = page.waitForResponse(response => response.url().endsWith('/api/dashboard/') && response.ok());
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  await expect(page.locator('.metric-value').first()).toContainText(/\d/);
}

// Regression check for the rendered operational surfaces. This checks normal
// text, including input placeholders, against computed CSS backgrounds. It is
// not a substitute for a complete WCAG audit (images and canvas are not text).
export async function expectNormalTextContrast(page, surface) {
  await page.evaluate(() => document.fonts.ready);
  const findings = await page.evaluate(() => {
    const root = document.querySelector('[role="dialog"]') || document.body;
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

test('les textes de connexion et des listes SAV ont un contraste minimal de 4,5:1', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Bienvenue sur PowerCare', exact: true })).toBeVisible();
  await expectNormalTextContrast(page, 'Connexion');
  await login(page, 'admin');
  await expectNormalTextContrast(page, 'Tableau de bord interne');
  const navigation = page.getByRole('navigation', { name: 'Navigation principale' });
  for (const label of ['Demandes SAV', 'Équipements', 'Interventions', 'Clients']) {
    await navigation.getByText(label, { exact: true }).click();
    await expect(page.getByRole('heading', { name: label, exact: true }).first()).toBeVisible();
    if (label === 'Clients') await expect(page.locator('.client-directory-table tbody tr').first()).toBeVisible();
    await expectNormalTextContrast(page, label);
  }
  // The dedicated E2E database contains only seeded or test-created fictional clients.
  await page.getByRole('button', { name: /^Consulter la fiche / }).first().click();
  const clientProfile = page.getByRole('dialog', { name: 'Fiche client', exact: true });
  await expect(clientProfile).toBeVisible();
  await expect(clientProfile.getByLabel('Actualisation de la fiche')).toHaveCount(0);
  await expectNormalTextContrast(page, 'Fiche client');
  await clientProfile.getByRole('button', { name: 'Fermer', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Importer des clients', exact: true }).click();
  const clientImport = page.getByRole('dialog', { name: 'Importer des clients', exact: true });
  await expect(clientImport.getByLabel('Fichier clients CSV', { exact: true })).toBeVisible();
  await expectNormalTextContrast(page, 'Formulaire import clients');
  await clientImport.getByRole('button', { name: 'Fermer', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await navigation.getByText('Contrats & garanties', { exact: true }).click();
  await page.getByRole('button', { name: /^Garanties\s+\d+$/ }).click();
  await expectNormalTextContrast(page, 'Garanties');
  await navigation.getByText('Équipements', { exact: true }).click();
  await page.getByRole('button', { name: 'Nouvel équipement', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expectNormalTextContrast(page, 'Formulaire équipement');
});

test('les textes du portail client restent lisibles sur téléphone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, 'client');
  await expectNormalTextContrast(page, 'Tableau de bord client mobile');
  await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await expectNormalTextContrast(page, 'Menu client mobile');
  await page.getByRole('navigation', { name: 'Navigation principale' }).getByText('Équipements', { exact: true }).click();
  await expectNormalTextContrast(page, 'Parc client mobile');
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2)).toBeFalsy();
});
