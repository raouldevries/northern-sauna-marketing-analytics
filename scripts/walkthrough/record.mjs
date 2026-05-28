import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

// Streamlit Cloud serves the app inside an iframe at /~/+/<page>.
// Navigating to that inner URL directly bypasses the wrapper and gives us a
// clean main-frame DOM (no status-page iframe in the viewport).
const PUBLIC_BASE = process.env.WALKTHROUGH_BASE ?? 'https://northern-sauna-marketing-analytics.streamlit.app';
const BASE = `${PUBLIC_BASE}/~/+`;
const TOP_DWELL_MS = Number(process.env.WALKTHROUGH_TOP_DWELL_MS ?? 1800);
const SCROLL_MS = Number(process.env.WALKTHROUGH_SCROLL_MS ?? 3500);
const BOTTOM_DWELL_MS = Number(process.env.WALKTHROUGH_BOTTOM_DWELL_MS ?? 1500);
const NAV_TIMEOUT_MS = 60_000;
const OUT_DIR = path.resolve(process.env.WALKTHROUGH_OUT_DIR ?? 'video');

// Streamlit page hrefs — map straight to /~/+/<slug>.
// Sidebar order, skipping the AI page (empty in demo mode).
const PAGES = [
  { slug: 'overview', label: 'Overview' },
  { slug: 'turnover', label: 'Turnover' },
  { slug: 'bookings', label: 'Bookings' },
  { slug: 'customers', label: 'Customers' },
  { slug: 'members', label: 'Members' },
  { slug: 'capacity', label: 'Capacity' },
  { slug: 'promotions', label: 'Promotions' },
  { slug: 'marketing', label: 'Marketing' },
  { slug: 'organic_seo', label: 'Organic & SEO' },
  { slug: 'reviews', label: 'Reviews' },
];

fs.mkdirSync(OUT_DIR, { recursive: true });

const browser = await chromium.launch({ headless: true });

// Off-camera pre-warm: wake the Streamlit container before we start recording.
{
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  console.log('Pre-warming the Streamlit container…');
  await page.goto(`${BASE}/overview`, { waitUntil: 'networkidle', timeout: NAV_TIMEOUT_MS }).catch(() => {});
  await ctx.close();
}

const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: OUT_DIR, size: { width: 1920, height: 1080 } },
});
const page = await context.newPage();

async function smoothScrollToBottom(page, durationMs) {
  await page.evaluate(async (ms) => {
    // Streamlit's scroll container is <section data-testid="stMain">, not window.
    const target = document.querySelector('[data-testid="stMain"]');
    if (!target) return;
    const start = target.scrollTop;
    const end = target.scrollHeight - target.clientHeight;
    const distance = Math.max(0, end - start);
    if (distance < 20) return;
    const t0 = performance.now();
    await new Promise((resolve) => {
      const step = (now) => {
        const t = Math.min(1, (now - t0) / ms);
        const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        target.scrollTop = start + distance * e;
        if (t < 1) requestAnimationFrame(step);
        else resolve();
      };
      requestAnimationFrame(step);
    });
  }, durationMs);
}

async function waitForStreamlitIdle(page) {
  await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
  await page
    .waitForFunction(
      () => {
        const w = document.querySelector('[data-testid="stStatusWidget"]');
        if (!w) return true;
        const t = (w.textContent ?? '').toLowerCase();
        return !t.includes('running');
      },
      { timeout: 30_000 }
    )
    .catch(() => {});
}

// Direct URL navigation is broken: app.py re-runs on every load and forces
// st.switch_page back to overview. Sidebar clicks use Streamlit's internal
// routing and don't re-trigger the entry script.
async function tourPage({ slug, label }, isInitial) {
  if (isInitial) {
    console.log(`→ ${label}  (initial load)`);
    await page.goto(`${BASE}/${slug}`, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT_MS });
  } else {
    console.log(`→ ${label}  (click [href="${slug}"])`);
    const link = page.locator(`[data-testid="stPageLink-NavLink"][href="${slug}"]`).first();
    await link.waitFor({ state: 'visible', timeout: 15_000 });
    await link.click();
    await page
      .waitForFunction(
        (expected) => {
          const h = document.querySelector('h1, h2');
          return h && h.textContent?.trim().toLowerCase().startsWith(expected.toLowerCase());
        },
        label.split(' ')[0],
        { timeout: 20_000 }
      )
      .catch(() => {});
  }
  await waitForStreamlitIdle(page);
  // Make sure we start at the top in case Streamlit kept scroll position.
  await page.evaluate(() => {
    const m = document.querySelector('[data-testid="stMain"]');
    if (m) m.scrollTop = 0;
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(TOP_DWELL_MS);
  await smoothScrollToBottom(page, SCROLL_MS);
  await page.waitForTimeout(BOTTOM_DWELL_MS);
}

for (let i = 0; i < PAGES.length; i++) {
  try {
    await tourPage(PAGES[i], i === 0);
  } catch (err) {
    console.warn(`   ! ${PAGES[i].label}: ${err.message}`);
  }
}

await context.close();
await browser.close();

const files = fs
  .readdirSync(OUT_DIR)
  .filter((f) => f.endsWith('.webm'))
  .map((f) => ({ f, mtime: fs.statSync(path.join(OUT_DIR, f)).mtimeMs }))
  .sort((a, b) => b.mtime - a.mtime);

if (files.length) {
  const latest = path.join(OUT_DIR, files[0].f);
  console.log(`\nVideo saved: ${latest}`);
} else {
  console.error('No video file produced — check Playwright logs above.');
  process.exit(1);
}
