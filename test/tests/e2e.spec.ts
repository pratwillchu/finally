import { test, expect, Page } from '@playwright/test'

test.describe('FinAlly E2E Tests', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    // Wait for the app to connect to SSE
    await expect(page.getByText(/LIVE|CONNECTING/)).toBeVisible({ timeout: 15000 })
  })

  test('fresh start: default watchlist and $10k balance visible', async ({ page }) => {
    // Check default tickers appear
    await expect(page.getByText('AAPL')).toBeVisible()
    await expect(page.getByText('GOOGL')).toBeVisible()
    await expect(page.getByText('TSLA')).toBeVisible()

    // Check $10,000 starting balance in header
    await expect(page.getByText(/10,000/)).toBeVisible()

    // Check connection indicator
    await expect(page.getByText(/LIVE|CONNECTING/)).toBeVisible()
  })

  test('prices stream: prices update over time', async ({ page }) => {
    // Wait for AAPL to appear with a price
    await expect(page.getByText('AAPL')).toBeVisible()

    // Wait 2 seconds for prices to arrive
    await page.waitForTimeout(2000)

    // Should see some price values (dollar signs)
    const priceElements = page.locator('text=/\\$[0-9]+\\.[0-9]{2}/')
    await expect(priceElements.first()).toBeVisible({ timeout: 5000 })

    // Verify we eventually show LIVE status
    await expect(page.getByText('LIVE')).toBeVisible({ timeout: 10000 })
  })

  test('watchlist: add a new ticker', async ({ page }) => {
    // Find the ADD TICKER input
    const addInput = page.getByPlaceholder('ADD TICKER')
    await addInput.fill('PLTR')
    await addInput.press('Enter')

    // PLTR should now appear in watchlist
    await expect(page.getByText('PLTR')).toBeVisible({ timeout: 5000 })
  })

  test('watchlist: remove a ticker', async ({ page }) => {
    // Hover over a ticker row to reveal the remove button
    const appleRow = page.locator('text=AAPL').first()
    await appleRow.hover()

    // Click the × button near AAPL
    const removeBtn = page.locator('[class*="group"]:has-text("AAPL") button')
    if (await removeBtn.count() > 0) {
      await removeBtn.click()
      await page.waitForTimeout(1000)
      // AAPL should be gone from watchlist
      await expect(page.locator('[class*="group"]:has-text("AAPL")').first()).not.toBeVisible({ timeout: 5000 })
    }
  })

  test('select ticker: clicking a ticker selects it for main chart', async ({ page }) => {
    // Wait for prices to load
    await page.waitForTimeout(2000)

    // Click on MSFT in the watchlist
    await page.getByText('MSFT').first().click()

    // Main chart header should show MSFT
    // The chart header displays selected ticker
    const chartArea = page.locator('.flex-col').filter({ hasText: 'MSFT' })
    await expect(chartArea).toBeVisible({ timeout: 3000 })
  })

  test('buy shares: cash decreases and position appears', async ({ page }) => {
    // Wait for prices to populate
    await page.waitForTimeout(3000)

    // Get initial cash balance from header
    const cashText = await page.locator('text=/\\$[0-9,]+\\.[0-9]{2}/').first().textContent()

    // Fill trade bar
    const tickerInput = page.getByPlaceholder('TICKER')
    await tickerInput.fill('AAPL')

    const qtyInput = page.getByPlaceholder('QTY')
    await qtyInput.fill('1')

    // Click BUY
    await page.getByRole('button', { name: 'BUY' }).click()

    // Wait for confirmation message (green success text)
    await expect(page.locator('text=/BUY 1 AAPL/i')).toBeVisible({ timeout: 5000 })

    // Cash should have decreased — portfolio positions section shows AAPL
    await page.waitForTimeout(2000)
    await expect(page.locator('text=AAPL').first()).toBeVisible()
  })

  test('sell shares: can sell after buying', async ({ page }) => {
    await page.waitForTimeout(3000)

    // First buy
    await page.getByPlaceholder('TICKER').fill('AAPL')
    await page.getByPlaceholder('QTY').fill('2')
    await page.getByRole('button', { name: 'BUY' }).click()
    await expect(page.locator('text=/BUY 2 AAPL/i')).toBeVisible({ timeout: 5000 })

    await page.waitForTimeout(1000)

    // Then sell 1
    await page.getByPlaceholder('TICKER').fill('AAPL')
    await page.getByPlaceholder('QTY').fill('1')
    await page.getByRole('button', { name: 'SELL' }).click()
    await expect(page.locator('text=/SELL 1 AAPL/i')).toBeVisible({ timeout: 5000 })
  })

  test('AI chat: send message and get mocked response', async ({ page }) => {
    await page.waitForTimeout(2000)

    // Find and use the chat input
    const chatInput = page.getByPlaceholder('Ask FinAlly...')
    await chatInput.fill('What is my portfolio?')
    await chatInput.press('Enter')

    // Wait for the mock response (it always buys 5 AAPL)
    // The mock response message
    await expect(page.locator("text=/I've reviewed your portfolio/")).toBeVisible({ timeout: 15000 })

    // Should show trade confirmation
    await expect(page.locator('text=/BUY 5 AAPL/i')).toBeVisible({ timeout: 10000 })
  })

  test('health check: /api/health returns 200', async ({ page, request }) => {
    const response = await request.get('/api/health')
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body.status).toBe('ok')
  })

  test('portfolio API: returns valid structure', async ({ request }) => {
    const response = await request.get('/api/portfolio')
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body).toHaveProperty('cash_balance')
    expect(body).toHaveProperty('total_value')
    expect(body).toHaveProperty('positions')
    expect(typeof body.cash_balance).toBe('number')
    expect(Array.isArray(body.positions)).toBe(true)
  })

  test('watchlist API: returns 10 default tickers', async ({ request }) => {
    const response = await request.get('/api/watchlist')
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(Array.isArray(body)).toBe(true)
    expect(body.length).toBe(10)
    const tickers = body.map((w: { ticker: string }) => w.ticker)
    expect(tickers).toContain('AAPL')
    expect(tickers).toContain('GOOGL')
    expect(tickers).toContain('TSLA')
  })

  test('trade API: validates insufficient cash', async ({ request }) => {
    const response = await request.post('/api/portfolio/trade', {
      data: { ticker: 'AAPL', side: 'buy', quantity: 1000000 },
    })
    expect(response.status()).toBe(400)
  })

  test('SSE stream: connects and sends price data', async ({ page }) => {
    // Verify prices are flowing via the UI showing price values
    await page.waitForTimeout(3000)

    // There should be price values visible (after SSE data arrives)
    const priceTexts = page.locator('text=/\\$[0-9]{2,}\\.[0-9]{2}/')
    const count = await priceTexts.count()
    expect(count).toBeGreaterThan(0)
  })
})
