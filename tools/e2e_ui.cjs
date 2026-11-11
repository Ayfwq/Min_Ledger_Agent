/**
 * Browser end-to-end smoke test (Playwright, Chromium).
 *
 * Prerequisites:
 *   npm i -g playwright && npx playwright install chromium
 *   a running instance, e.g. http://127.0.0.1:18080
 *
 * Usage:
 *   BASE=http://127.0.0.1:18080 node tools/e2e_ui.cjs
 *   # Windows without global playwright:
 *   CHROME_PATH="C:\\...\\chrome.exe" BASE=... node tools/e2e_ui.cjs
 *
 * Covers: clarification -> confirm, edit conflict -> force override,
 * reject, bills search, review filters.
 */
const { chromium } = require('playwright')

const BASE = process.env.BASE || 'http://127.0.0.1:18080'
const HEADLESS = process.env.HEADFUL !== '1'

function log(...args) {
  console.log('[e2e]', ...args)
}

async function createInput(page, text) {
  await page.goto(BASE + '/', { waitUntil: 'networkidle' })
  await page.locator('textarea').fill(text)
  await page.getByRole('button', { name: '开始识别' }).click()
  await page.waitForURL(/\/inputs\//, { timeout: 20000 })
  await page.waitForSelector('text=草稿', { timeout: 60000 })
}

async function main() {
  const browser = await chromium.launch({
    headless: HEADLESS,
    executablePath: process.env.CHROME_PATH || undefined,
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 980 }, locale: 'zh-CN' })
  const errors = []
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
  page.on('console', (m) => {
    // 409 from the intentional conflict check is expected.
    if (m.type() === 'error' && !m.text().includes('409')) errors.push('console: ' + m.text())
  })

  // 1) missing amount -> clarification -> confirm
  await createInput(page, '昨天吃饭花了点钱')
  const amount = page.getByPlaceholder('例如：35.5')
  await amount.waitFor({ timeout: 90000 })
  await amount.fill('40')
  await page.getByRole('button', { name: '提交' }).click()
  await page.waitForSelector('text=已提交', { timeout: 30000 })
  await page.waitForTimeout(2500)
  await page.getByRole('button', { name: '确认入账' }).first().click()
  await page.locator('.el-message-box').waitFor({ timeout: 10000 })
  await page.locator('.el-message-box').getByRole('button', { name: '确认入账' }).click()
  await page.waitForSelector('text=已生成正式账单', { timeout: 30000 })
  log('clarification -> confirm OK')

  // 2) extracted value -> edit triggers conflict dialog -> override -> reject
  await createInput(page, '2026-11-01 在星巴克花了 35.5 元')
  await page.getByRole('button', { name: '编辑' }).first().click()
  await page.locator('.el-dialog').waitFor({ timeout: 10000 })
  await page.locator('.el-dialog .el-input-number input').first().fill('40')
  await page.getByRole('button', { name: '保存修改' }).click()
  await page.locator('.el-message-box').waitFor({ timeout: 10000 })
  const boxText = await page.locator('.el-message-box').innerText()
  if (!boxText.includes('35.5')) throw new Error('conflict dialog did not show original value')
  await page.getByRole('button', { name: '确认覆盖' }).click()
  await page.waitForSelector('text=已保存', { timeout: 20000 })
  await page.waitForTimeout(1500)
  await page.getByRole('button', { name: '拒绝' }).first().click()
  await page.locator('.el-message-box').waitFor({ timeout: 10000 })
  await page.locator('.el-message-box').getByRole('button', { name: '拒绝' }).click()
  await page.waitForSelector('text=已拒绝', { timeout: 30000 })
  log('conflict override -> reject OK')

  // 3) bills page + search
  await page.goto(BASE + '/bills', { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  if (!(await page.locator('body').innerText()).includes('40.00')) throw new Error('bill missing')
  await page.getByPlaceholder('搜索商户 / 说明').fill('不存在的商户XYZ')
  await page.waitForTimeout(600)
  if ((await page.locator('body').innerText()).includes('40.00')) throw new Error('search filter failed')
  log('bills page + search OK')

  // 4) review filters
  await page.goto(BASE + '/review', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: /已拒绝/ }).click()
  await page.waitForTimeout(1000)
  if (!(await page.locator('body').innerText()).includes('已拒绝')) throw new Error('review filter failed')
  log('review filter OK')

  await browser.close()
  if (errors.length) {
    console.error('browser errors:', errors)
    process.exit(1)
  }
  console.log('[e2e] all UI scenarios passed')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
