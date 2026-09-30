import { devices, expect, test } from '@playwright/test'

test('mobile visitor can select email type and country, then submit a lead', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/connect?ref=playwright&utm_source=e2e&utm_medium=qr&utm_campaign=review')
  await expect(page.getByRole('heading', { name: /let.?s stay connected/i })).toBeVisible()
  await page.getByRole('link', { name: /enter details manually/i }).click()
  for (const width of [320, 360, 375, 390, 430]) {
    await page.setViewportSize({ width, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  await page.setViewportSize({ width: 390, height: 844 })

  await page.getByPlaceholder('e.g. Rachel Thomas').fill('Browser Review Contact')
  await page.getByPlaceholder('e.g. ABC Technologies').fill('E2E Example Company')
  await page.getByPlaceholder('e.g. VP Innovation').fill('Product Manager')
  const email = page.getByPlaceholder('you@company.com')
  await email.fill('review@gmail.com')
  await expect(page.getByLabel('Personal', { exact: true })).toBeChecked()
  await email.fill('review@example.com')
  await expect(page.getByLabel('Work', { exact: true })).toBeChecked()

  const country = page.locator('.PhoneInputCountrySelect')
  await country.selectOption('GB')
  const phone = page.locator('.PhoneInputInput')
  await phone.fill('791ab1123456')
  await expect(phone).not.toHaveValue(/[a-z]/i)
  await phone.fill('7911123456')
  await expect(phone).toHaveValue(/\+44/)

  await page.getByRole('button', { name: 'AI Agents' }).click()
  await page.getByLabel('What would you like to discuss?').selectOption('I need a demo')
  await page.getByRole('button', { name: /connect with latentsig/i }).click()
  await expect(page.getByRole('heading', { name: /thank you, browser/i })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('link', { name: /continue on whatsapp/i })).toHaveAttribute('href', /^https:\/\/wa\.me\//)
})

test('manual submission explains API failure and card scan offers recovery', async ({ page }) => {
  await page.route('**/api/v1/leads', route => route.abort())
  await page.goto('/connect/manual')
  await page.getByPlaceholder('e.g. Rachel Thomas').fill('Offline Review Contact')
  await page.getByPlaceholder('e.g. ABC Technologies').fill('Offline Test Company')
  await page.getByPlaceholder('e.g. VP Innovation').fill('Engineer')
  await page.getByPlaceholder('you@company.com').fill('offline-review@example.com')
  await page.locator('.PhoneInputInput').fill('+919876543210')
  await page.getByRole('button', { name: 'AI Agents' }).click()
  await page.getByLabel('What would you like to discuss?').selectOption('I need a demo')
  await page.getByRole('button', { name: /connect with latentsig/i }).click()
  await expect(page.getByRole('alert')).toContainText(/your details have not been sent/i)
  await expect(page.getByPlaceholder('e.g. Rachel Thomas')).toBeVisible()

  await page.unroute('**/api/v1/leads')
  await page.route('**/api/v1/ocr/business-card', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Local OCR is unavailable.' }) }))
  await page.goto('/connect/card')
  await page.locator('input[type=file]').nth(1).setInputFiles('../logo.png')
  await page.getByRole('button', { name: 'Scan business card' }).click()
  await expect(page.getByRole('alert')).toContainText(/local ocr is unavailable/i)
  await expect(page.getByRole('button', { name: 'Scan business card' })).toBeEnabled()
})

test('Other interest asks for details and the team can review them on the lead', async ({ page }) => {
  const suffix = Date.now().toString()
  const contactName = `Other Interest ${suffix.slice(-6)}`
  const details = 'RAG agent workflow for research'
  const feedback = 'The form was clear; ask about deployment options too.'
  await page.goto('/connect/manual')
  await page.getByPlaceholder('e.g. Rachel Thomas').fill(contactName)
  await page.getByPlaceholder('e.g. ABC Technologies').fill('Other Interest Example Ltd')
  await page.getByPlaceholder('e.g. VP Innovation').fill('Product Manager')
  await page.getByPlaceholder('you@company.com').fill(`other-interest-${suffix}@example.com`)
  await page.locator('.PhoneInputCountrySelect').selectOption('US')
  await page.locator('.PhoneInputInput').fill(`415555${suffix.slice(-4)}`)
  await page.getByRole('button', { name: 'Other', exact: true }).click()
  const detailsField = page.getByPlaceholder('e.g. RAG agent')
  await expect(detailsField).toBeVisible()
  const interestPrompt = page.getByText('What are you interested in? Explain in 5 words')
  await expect(interestPrompt).toBeVisible()
  const inlineInterestField = await page.locator('.message-field').filter({ has: interestPrompt }).evaluate(field => field.compareDocumentPosition(document.querySelector('.intent-field')!) & Node.DOCUMENT_POSITION_FOLLOWING)
  expect(inlineInterestField).toBeTruthy()
  await page.getByLabel('What would you like to discuss?').selectOption('I need a demo')
  await page.getByRole('button', { name: /connect with latentsig/i }).click()
  await expect(page.getByText('Please explain your interest in 5 words or fewer.')).toBeVisible()
  await detailsField.fill(details)
  await page.getByPlaceholder('Share your thoughts with us').fill(feedback)
  await page.getByRole('button', { name: /connect with latentsig/i }).click()
  await expect(page).toHaveURL(/\/connect\/thank-you$/)

  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  await page.goto('/admin/leads')
  await page.getByPlaceholder('Search name, company, email or phone').fill(contactName)
  await page.getByRole('link', { name: new RegExp(contactName) }).first().click()
  await expect(page.getByText(`Other interest: ${details}`, { exact: true })).toBeVisible()
  await expect(page.getByText(`Visitor feedback: ${feedback}`, { exact: true })).toBeVisible()
})

test('Other discussion shows its explanation and feedback inline', async ({ page }) => {
  const suffix = Date.now().toString()
  await page.goto('/connect/manual')
  await page.getByPlaceholder('e.g. Rachel Thomas').fill('Other Discussion Contact')
  await page.getByPlaceholder('e.g. ABC Technologies').fill('Other Discussion Example Ltd')
  await page.getByPlaceholder('e.g. VP Innovation').fill('Product Manager')
  await page.getByPlaceholder('you@company.com').fill(`other-discussion-${suffix}@example.com`)
  await page.locator('.PhoneInputCountrySelect').selectOption('US')
  await page.locator('.PhoneInputInput').fill(`415555${suffix.slice(-4)}`)
  await page.getByRole('button', { name: 'AI Agents' }).click()
  await page.getByLabel('What would you like to discuss?').selectOption('Other')
  const prompt = page.getByText('What would you like to discuss? Explain in 5 words')
  await expect(prompt).toBeVisible()
  const detailsField = page.getByPlaceholder('e.g. RAG agent')
  await expect(detailsField).toBeVisible()
  await expect(page.getByText('How did you feel? What could we improve?')).toBeVisible()
  await detailsField.fill('RAG agent for support')
  await expect(page.getByText('4 / 5 words')).toBeVisible()
  await page.getByPlaceholder('Share your thoughts with us').fill('Please add a link to learn about your services.')
  await page.getByRole('button', { name: /connect with latentsig/i }).click()
  await expect(page).toHaveURL(/\/connect\/thank-you$/)
})

test('local admin login accepts only an approved email and has no password or Google prompt', async ({ page }) => {
  await page.goto('/admin/login')
  await expect(page.getByLabel('Password')).toHaveCount(0)
  await expect(page.getByRole('link', { name: /continue with google/i })).toHaveCount(0)
  await page.getByPlaceholder('name@latentsig.com').fill('outside@example.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toContainText(/not on the team access list/i)
})

test('team member can sign in and admins can review captured leads', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/admin/login')
  await expect(page.getByLabel('Password')).toHaveCount(0)
  await expect(page.getByRole('link', { name: /continue with google/i })).toHaveCount(0)
  await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await page.goto('/admin/leads')
  await expect(page.getByRole('heading', { name: 'Leads', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Columns' }).click()
  await page.getByLabel('Lead ID').check()
  await page.getByLabel('Assigned to').check()
  await page.getByRole('button', { name: 'Columns' }).click()
  await expect(page.getByRole('columnheader', { name: 'Lead ID' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.setViewportSize({ width: 1280, height: 900 })
  const workbook = page.waitForEvent('download')
  await page.getByRole('button', { name: /Export Excel/ }).click()
  expect((await workbook).suggestedFilename()).toMatch(/\.xlsx$/)
  await expect(page.getByText('Browser Review Contact').first()).toBeVisible()
  await page.getByPlaceholder('Search name, company, email or phone').fill('Browser Review Contact')
  await page.getByRole('checkbox', { name: 'Select Browser Review Contact' }).check()
  await page.getByLabel('Assign selected leads').selectOption({ label: 'Bhoomika' })
  const assigned = page.waitForResponse(response => response.url().includes('/api/v1/admin/leads/bulk-assign') && response.status() === 200)
  await page.getByRole('button', { name: 'Apply assignment' }).click()
  await assigned
  await page.getByRole('checkbox', { name: 'Select Browser Review Contact' }).check()
  await page.getByLabel('Assign selected leads').selectOption('')
  const unassigned = page.waitForResponse(response => response.url().includes('/api/v1/admin/leads/bulk-assign') && response.status() === 200)
  await page.getByRole('button', { name: 'Apply assignment' }).click()
  await unassigned
  await page.getByRole('link', { name: /Browser Review Contact/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Browser Review Contact' })).toBeVisible()
  await expect(page.getByText('review@example.com')).toBeVisible()
  await expect(page.getByText(/Card uploaded for this submission/)).toHaveCount(0)
  await page.getByRole('button', { name: /sign out/i }).click()
  await page.getByPlaceholder('name@latentsig.com').fill('bhoomika@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  await page.goto('/admin/settings')
  await page.getByRole('button', { name: 'Show QR' }).first().click()
  await expect(page.getByRole('img', { name: 'QR code for bts-2026' })).toBeVisible()
  const captureHref = await page.getByRole('link', { name: 'Open capture link' }).first().getAttribute('href')
  expect(captureHref).toContain('event=bts-2026')
  expect(captureHref).toContain('utm_medium=qr')
  expect(new URL(captureHref!).protocol).toMatch(/^https?:$/)
  if (process.env.PLAYWRIGHT_EXPECTED_CAPTURE_ORIGIN) {
    expect(new URL(captureHref!).origin).toBe(process.env.PLAYWRIGHT_EXPECTED_CAPTURE_ORIGIN)
  }
  const qrImage = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download QR image' }).click()
  expect((await qrImage).suggestedFilename()).toBe('bts-2026-capture-qr.svg')
  await page.goto('/admin/leads')
  await page.getByPlaceholder('Search name, company, email or phone').fill('Browser Review Contact')
  await expect(page.getByRole('link', { name: /Browser Review Contact/ }).first()).toBeVisible()
  await page.getByRole('link', { name: /Browser Review Contact/ }).first().click()
  await expect(page.getByLabel('Status')).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('public capture and admin leads fit phone, tablet, laptop, and desktop viewports', async ({ page }) => {
  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)

  const viewports = [
    { label: 'small phone', width: 320, height: 720 },
    { label: 'phone', width: 390, height: 844 },
    { label: 'large phone', width: 430, height: 932 },
    { label: 'tablet portrait', width: 768, height: 1024 },
    { label: 'tablet landscape', width: 1024, height: 768 },
    { label: 'laptop', width: 1366, height: 768 },
    { label: 'desktop', width: 1920, height: 1080 },
  ]
  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await page.goto('/connect/manual')
    await expect(page.getByRole('heading', { name: /tell us a little about yourself/i })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${viewport.label}: public form has no horizontal overflow`).toBe(true)

    await page.goto('/admin/leads')
    await expect(page.getByRole('heading', { name: 'Leads', exact: true })).toBeVisible()
    const overflowDetails = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      elements: [...document.querySelectorAll('body *')].map(element => {
        const rect = element.getBoundingClientRect()
        return { tag: element.tagName, className: typeof element.className === 'string' ? element.className : '', text: element.textContent?.trim().slice(0, 48), left: Math.round(rect.left), right: Math.round(rect.right), width: Math.round(rect.width) }
      }).filter(element => element.right > window.innerWidth + 1).slice(0, 12),
    }))
    expect(overflowDetails.scrollWidth <= overflowDetails.viewportWidth, `${viewport.label}: admin leads overflow ${JSON.stringify(overflowDetails)}`).toBe(true)
  }
})

test('Pixel 10, iPhone 17, and iPhone 18-size emulation can submit leads and open admin review', async ({ browser }) => {
  const deviceProfiles = [
    { name: 'Pixel 10', profile: devices['Pixel 10'] },
    { name: 'iPhone 17', profile: devices['iPhone 17'] },
    // Playwright has no iPhone 18 descriptor yet; use its iPhone 17 viewport profile.
    { name: 'iPhone 18-size', profile: devices['iPhone 17'] },
  ] as const
  for (const { name: deviceName, profile } of deviceProfiles) {
    const context = await browser.newContext({ ...profile })
    const page = await context.newPage()
    const suffix = `${deviceName.replace(/\W/g, '').toLowerCase()}-${Date.now()}`
    const contactName = `Mobile ${deviceName} Review`
    try {
      await page.goto('/connect/manual')
      await page.getByPlaceholder('e.g. Rachel Thomas').fill(contactName)
      await page.getByPlaceholder('e.g. ABC Technologies').fill('LatentSig Mobile Review Ltd')
      await page.getByPlaceholder('e.g. VP Innovation').fill('Product Manager')
      await page.getByPlaceholder('you@company.com').fill(`${suffix}@example.com`)
      await page.locator('.PhoneInputCountrySelect').selectOption('US')
      await page.locator('.PhoneInputInput').fill('4155550123')
      await page.getByRole('button', { name: 'AI Agents' }).click()
      await page.getByLabel('What would you like to discuss?').selectOption('I need a demo')
      await page.getByRole('button', { name: /connect with latentsig/i }).click()
      await expect(page.getByRole('heading', { name: /thank you, mobile/i })).toBeVisible({ timeout: 15_000 })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${deviceName}: confirmation has no horizontal overflow`).toBe(true)

      await page.goto('/admin/login')
      await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
      await page.getByRole('button', { name: 'Sign in' }).click()
      await expect(page).toHaveURL(/\/admin\/dashboard$/)
      await page.goto('/admin/leads')
      await page.getByPlaceholder('Search name, company, email or phone').fill(contactName)
      await expect(page.getByRole('link', { name: new RegExp(contactName) }).first()).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${deviceName}: admin leads has no horizontal overflow`).toBe(true)
    } finally {
      await context.close()
    }
  }
})

test('business-card upload uses local OCR and opens an editable review step', async ({ page }) => {
  const testContactId = Date.now()
  const cardEmail = `two-sided-card-${testContactId}@example.com`
  const cardPhone = `+919${String(testContactId).slice(-9)}`
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/connect/card')
  await expect(page.getByRole('button', { name: 'Take Photo' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Upload Image' }).first()).toBeVisible()
  await expect(page.locator('input[type=file][capture="environment"]')).toHaveCount(2)
  await page.locator('input[type=file][capture="environment"]').first().setInputFiles('../logo.png')
  await page.locator('input[type=file]').nth(3).setInputFiles('../logo.png')
  await expect(page.getByText('logo.png')).toHaveCount(2)
  await page.getByRole('button', { name: 'Scan business card' }).click()
  await expect(page).toHaveURL(/\/connect\/card\/review$/,{timeout:30_000})
  await expect(page.getByRole('heading', { name: /please confirm your details/i })).toBeVisible()
  await expect(page.getByPlaceholder('e.g. Rachel Thomas')).toBeEditable()
  await expect(page.getByRole('button', { name: 'AI Agents' })).toBeVisible()
  await page.getByPlaceholder('e.g. Rachel Thomas').fill('Two Sided Card Browser Lead')
  await page.getByPlaceholder('e.g. ABC Technologies').fill('Two Sided Example Ltd')
  await page.getByPlaceholder('e.g. VP Innovation').fill('Founder')
  await page.getByPlaceholder('you@company.com').fill(cardEmail)
  await page.locator('.PhoneInputInput').fill(cardPhone)
  await page.getByRole('button', { name: 'AI Agents' }).click()
  await page.getByLabel('What would you like to discuss?').selectOption('I need a demo')
  await page.getByRole('button', { name: /connect with latentsig/i }).click()
  await expect(page.getByRole('heading', { name: /thank you, two/i })).toBeVisible({ timeout: 15_000 })
  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  await page.goto('/admin/leads')
  await page.getByPlaceholder('Search name, company, email or phone').fill('Two Sided Card Browser Lead')
  await page.getByRole('link', { name: /Two Sided Card Browser Lead/ }).first().click()
  await expect(page.getByText('Card uploaded for this submission')).toBeVisible()
  await page.getByRole('button', { name: /View front/ }).first().click()
  await expect(page.getByRole('dialog', { name: /front of uploaded business card/i })).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Close' }).click()
  await expect(page.getByRole('button', { name: /View back/ }).first()).toBeVisible()
})

test('Android rear-camera capture input works in a mobile browser and opens OCR review', async ({ browser }) => {
    const mobileContext = await browser.newContext({ ...devices['Pixel 7'] })
    const page = await mobileContext.newPage()
    try {
    await page.route('**/api/v1/ocr/business-card', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        full_name: { value: 'Camera Review Contact' },
        company: { value: 'Mobile Camera Example Ltd' },
        job_title: { value: 'Product Manager' },
        email: { value: 'camera-review@example.com' },
        phone: { value: '+14155550123' },
        website: { value: 'https://example.com' },
      }),
    }))
    await page.goto('/connect/card?event=bts-2026&ref=booth&utm_medium=qr')
    await expect(page.getByRole('button', { name: 'Take Photo' }).first()).toBeVisible()
    const cameraInput = page.locator('input[type=file][capture="environment"]').first()
    await expect(cameraInput).toHaveAttribute('accept', 'image/jpeg,image/png,image/webp')
    await cameraInput.setInputFiles('../logo.png')
    await expect(page.getByText('logo.png')).toBeVisible()
    await page.getByRole('button', { name: 'Scan business card' }).click()
    await expect(page).toHaveURL(/\/connect\/card\/review(?:\?|$)/,{timeout:30_000})
    await expect(page.getByRole('heading', { name: /please confirm your details/i })).toBeVisible()
    } finally {
      await mobileContext.close()
    }
})
