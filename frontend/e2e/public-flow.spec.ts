import { devices, expect, test, type Page } from '@playwright/test'

async function acceptNotice(page: Page, allowFollowUp = true) {
  const checkbox = page.getByRole('checkbox', { name: /I agree LatentSig may store and process these details/ })
  if (await checkbox.count()) await checkbox.check()
  if (allowFollowUp) {
    const followUp = page.getByRole('checkbox', { name: /You may contact me about this enquiry/ })
    if (await followUp.count()) await followUp.check()
  }
}

async function acceptAiImageNotice(page: Page) {
  const checkbox = page.getByRole('checkbox', { name: /I agree LatentSig may process this card image/ })
  if (await checkbox.count()) await checkbox.check()
}

test('event QR landing offers card scan or manual entry and preserves attribution', async ({ page }) => {
  await page.goto('/connect?event=bts-2026&session=expo-floor&ref=booth&utm_source=latentsig&utm_medium=qr')
  const scanCard = page.getByRole('link', { name: /scan \/ upload business card/i })
  const manualEntry = page.getByRole('link', { name: /enter details manually/i })
  await expect(page.getByText('Choose one: scan your business card and review the details, or enter them yourself.')).toBeVisible()
  await expect(scanCard).toHaveAttribute('href', /\/connect\/card\?event=bts-2026/)
  await expect(manualEntry).toHaveAttribute('href', /\/connect\/manual\?event=bts-2026/)
  await scanCard.click()
  await expect(page).toHaveURL(/\/connect\/card\?event=bts-2026/)
  await expect(page.getByRole('button', { name: 'Take Photo' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: /i'll enter my details instead/i })).toBeVisible()
})

test('research workspace defaults to BTS 2026 and explains when it has no records', async ({ page }) => {
  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bhoomika@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  const eventsResponse = page.waitForResponse(response => response.url().endsWith('/api/v1/admin/events') && response.ok())
  await page.goto('/admin/research')
  const events = await (await eventsResponse).json()
  const bts = events.find((event: { slug: string }) => event.slug === 'bts-2026')
  expect(bts).toBeTruthy()
  await expect(page.getByLabel('Event')).toHaveValue(bts.id)
  await expect(page.getByRole('heading', { name: 'Imported registrants' })).toBeVisible()
  const importsResponse = await page.request.get(`/api/v1/admin/events/${bts.id}/research/imports`)
  const imports = await importsResponse.json()
  if (!imports.length) await expect(page.getByText('No research workbook has been imported for this event yet.')).toBeVisible()
  if (imports[0]?.status === 'imported' && imports[0].row_count > 50) {
    await expect(page.locator('.research-results-meta')).toContainText(`of ${imports[0].row_count} registrant rows`)
    await page.getByRole('button', { name: 'Next registrant page' }).click()
    await expect(page.locator('.research-results-meta')).toContainText('Showing 51–100 of')
  }
  if (imports[0]?.status === 'imported' && imports[0].sheet_names.length) {
    const worksheet = imports[0].sheet_names[0]
    const filtered = await page.request.get(`/api/v1/admin/events/${bts.id}/research/registrants?sheet=${encodeURIComponent(worksheet)}&page_size=1`)
    const total = (await filtered.json()).total
    await page.locator('.research-sheet-filter').selectOption(worksheet)
    await expect(page.locator('.research-results-meta')).toContainText(`of ${total} registrant rows`)
    await expect(page.locator('.research-results-meta')).toContainText(worksheet)
  }
})

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
  await acceptNotice(page)
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
  await acceptNotice(page)
  await page.getByRole('button', { name: /connect with latentsig/i }).click()
  await expect(page.getByRole('alert')).toContainText(/your details have not been sent/i)
  await expect(page.getByPlaceholder('e.g. Rachel Thomas')).toBeVisible()

  await page.unroute('**/api/v1/leads')
  await page.route('**/api/v1/ocr/business-card', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Card scanning is temporarily unavailable.' }) }))
  await page.goto('/connect/card')
  await page.locator('input[type=file]').nth(1).setInputFiles('../logo.png')
  await acceptAiImageNotice(page)
  await page.getByRole('button', { name: 'Scan business card' }).click()
  await expect(page.getByRole('alert')).toContainText(/card scanning is temporarily unavailable/i)
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
  await acceptNotice(page)
  await page.getByRole('button', { name: /connect with latentsig/i }).click()
  await expect(page.getByText('Please explain your interest in 5 words or fewer.')).toBeVisible()
  await detailsField.fill(details)
  await page.getByPlaceholder('Share a little context about your request').fill(feedback)
  await acceptNotice(page)
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
  await acceptNotice(page)
  const prompt = page.getByText('What would you like to discuss? Explain in 5 words')
  await expect(prompt).toBeVisible()
  const detailsField = page.getByPlaceholder('e.g. RAG agent')
  await expect(detailsField).toBeVisible()
  await expect(page.getByText('Anything else you’d like us to know?')).toBeVisible()
  await detailsField.fill('RAG agent for support')
  await expect(page.getByText('4 / 5 words')).toBeVisible()
  await page.getByPlaceholder('Share a little context about your request').fill('Please add a link to learn about your services.')
  await acceptNotice(page)
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
  // Provision the second allowlisted team member in the disposable test database
  // so the assignment workflow has an active assignee to choose.
  const seedMember = await page.request.post('/api/v1/auth/email-login', { data: { email: 'bhoomika@latentsig.com' } })
  expect(seedMember.ok()).toBeTruthy()
  const seedLogout = await page.request.post('/api/v1/auth/logout')
  expect(seedLogout.ok()).toBeTruthy()
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
  await page.getByLabel('Meeting date and time').fill('2026-11-18T10:30')
  await page.getByLabel('Meeting status').selectOption('requested')
  await page.getByLabel('Meeting owner').selectOption({ label: 'Bhoomika' })
  await page.getByLabel('Topics').fill('Agentic AI, annotation')
  await page.getByLabel('Demo presented').check()
  await page.getByLabel('Notes').fill('Reviewed the research workflow.')
  await page.getByLabel('Next steps').fill('Share the demo deck.')
  await page.getByLabel('Follow-up due').fill('2026-11-20')
  const meetingResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url().match(/\/api\/v1\/admin\/leads\/[^/]+\/meetings$/) !== null && response.status() === 201)
  await page.getByRole('button', { name: 'Record meeting' }).click()
  const meeting = await (await meetingResponse).json()
  await expect(page.getByText(/requested · Bhoomika/)).toBeVisible()
  await expect(page.getByText('Share the demo deck.')).toBeVisible()
  const confirmMeeting = page.waitForResponse(response => response.request().method() === 'PATCH' && response.url().endsWith(`/api/v1/admin/meetings/${meeting.id}`) && response.status() === 200)
  await page.getByLabel(`Status for meeting ${meeting.id}`).selectOption('confirmed')
  await confirmMeeting
  await expect(page.getByText(/confirmed · Bhoomika/)).toBeVisible()
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
  const expectedCaptureOrigin = process.env.PLAYWRIGHT_EXPECTED_CAPTURE_ORIGIN
    || process.env.VITE_PUBLIC_SITE_URL
    || new URL(process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173').origin
  expect(new URL(captureHref!).origin).toBe(expectedCaptureOrigin)
  const qrImage = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download QR image' }).click()
  expect((await qrImage).suggestedFilename()).toBe('bts-2026-capture-qr.svg')
  await page.goto('/admin/leads')
  await page.getByPlaceholder('Search name, company, email or phone').fill('Browser Review Contact')
  await expect(page.getByRole('link', { name: /Browser Review Contact/ }).first()).toBeVisible()
  await page.getByRole('link', { name: /Browser Review Contact/ }).first().click()
  await expect(page.locator('.admin-field').filter({ hasText: 'Status' }).locator('select')).toBeVisible()
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
      await acceptNotice(page)
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

test('business-card upload opens an editable review step', async ({ page }) => {
  await page.route('**/api/v1/ocr/business-card', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      full_name: { value: 'Two Sided Card Browser Lead' },
      company: { value: 'Two Sided Example Ltd' },
      job_title: { value: 'Founder' },
      email: { value: 'two-sided-card@example.com' },
      email_type: { value: 'work' },
      phone: { value: '+919876543210' },
      website: { value: 'https://example.com' },
      address: { value: 'Bengaluru, India' },
      is_template: false,
      warnings: [],
      uncertain_fields: [],
    }),
  }))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/connect/card')
  await expect(page.getByRole('button', { name: 'Take Photo' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Upload Image' }).first()).toBeVisible()
  await expect(page.locator('input[type=file][capture="environment"]')).toHaveCount(2)
  await page.locator('input[type=file][capture="environment"]').first().setInputFiles('../logo.png')
  await page.locator('input[type=file]').nth(3).setInputFiles('../logo.png')
  await expect(page.getByText('logo.png')).toHaveCount(2)
  await acceptAiImageNotice(page)
  await page.getByRole('button', { name: 'Scan business card' }).click()
  await expect(page).toHaveURL(/\/connect\/card\/review$/)
  await expect(page.getByRole('heading', { name: /please confirm your details/i })).toBeVisible()
  await expect(page.getByPlaceholder('e.g. Rachel Thomas')).toHaveValue('Two Sided Card Browser Lead')
  await expect(page.getByPlaceholder('e.g. ABC Technologies')).toHaveValue('Two Sided Example Ltd')
  await expect(page.getByPlaceholder('you@company.com')).toHaveValue('two-sided-card@example.com')
  await expect(page.getByPlaceholder('Street, city, country')).toHaveValue('Bengaluru, India')
  await expect(page.getByRole('button', { name: 'AI Agents' })).toBeVisible()
})

test('admin can flag template card scans as synthetic and they require identity review', async ({ page }) => {
  const captureId = '18ef7d2c-7ff7-4cff-b438-44e9bb8df574'
  let uploadBody = ''
  await page.route('**/api/v1/admin/card-captures', async route => {
    if (route.request().method() !== 'POST') return route.continue()
    uploadBody = (await route.request().postDataBuffer())?.toString('utf8') || ''
    const eventId = uploadBody.match(/name="event_id"\r\n\r\n([^\r\n]+)/)?.[1]
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        id: captureId,
        event_id: eventId,
        event_name: 'Bengaluru Tech Summit 2026',
        original_filename: 'logo.png',
        status: 'template_detected',
        ocr: { is_template: true, full_name: null, company: null, job_title: null, email: null, phone: null, website: null, address: null, warnings: ['This image looks like a card template or mockup.'] },
        synthetic_test: true,
        exclude_from_analytics: true,
        candidates: [],
      }),
    })
  })
  await page.route(`**/api/v1/admin/card-captures/${captureId}/image`, route => route.fulfill({ status: 404, body: '' }))
  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  await page.goto('/admin/card-capture')
  const syntheticToggle = page.getByRole('checkbox', { name: /Mark this capture as a synthetic test/ })
  await expect(syntheticToggle).toBeVisible()
  await page.locator('.capture-form > label').first().locator('select').selectOption({ label: 'Bengaluru Tech Summit 2026' })
  await page.locator('input[type=file][capture="environment"]').setInputFiles('../logo.png')
  await syntheticToggle.check()
  await expect(page.getByText(/External AI OCR is disabled by the current staff-card policy, including for synthetic tests/)).toBeVisible()
  await expect(page.getByLabel(/visitor explicitly agreed to AI processing/i)).toHaveCount(0)
  await page.getByRole('button', { name: 'Scan & Save Business Card' }).click()
  await expect(page.getByText(/This image looks like a designed sample or template/)).toBeVisible()
  await expect(page.getByText('Synthetic test capture — excluded from event analytics.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save as lead' })).toBeDisabled()
  expect(uploadBody).toContain('name="synthetic_test"\r\n\r\ntrue')
  expect(uploadBody).toContain('name="event_id"\r\n\r\n')
})

test('Android rear-camera capture input opens the AI review step', async ({ browser }) => {
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
    await acceptAiImageNotice(page)
    await page.getByRole('button', { name: 'Scan business card' }).click()
    await expect(page).toHaveURL(/\/connect\/card\/review(?:\?|$)/,{timeout:30_000})
    await expect(page.getByRole('heading', { name: /please confirm your details/i })).toBeVisible()
    } finally {
      await mobileContext.close()
    }
})
