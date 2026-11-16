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

test('research workspace separates worksheets and searches unified attendee profiles', async ({ page }) => {
  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bhoomika@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  const eventsResponse = page.waitForResponse(response => response.url().endsWith('/api/v1/admin/events') && response.ok())
  await page.goto('/admin/research')
  const events = await (await eventsResponse).json()
  const bts = events.find((event: { slug: string }) => event.slug === 'bts-2026')
  expect(bts).toBeTruthy()
  await expect(page.getByLabel('Event', { exact: true })).toHaveValue(bts.id)
  await expect(page.getByRole('heading', { name: 'Research records' })).toBeVisible()
  const sheetsResponse = await page.request.get(`/api/v1/admin/events/${bts.id}/research/sheets`)
  const summary = await sheetsResponse.json()
  if (!summary.sheets.length) {
    await expect(page.getByText('No research workbook has been imported for this event yet.')).toBeVisible()
    return
  }
  for (const sheet of summary.sheets) {
    const label = sheet.sheet_name.toLowerCase() === 'registrants' ? 'All registrants' : sheet.sheet_name
    await expect(page.getByRole('tab', { name: new RegExp(label) })).toBeVisible()
    await expect(page.getByRole('tab', { name: new RegExp(label) })).toContainText(sheet.row_count.toLocaleString())
  }
  for (const width of [320, 375, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  const registrantsSheet = summary.sheets.find((sheet: { sheet_name: string }) => sheet.sheet_name.toLowerCase() === 'registrants')
  if (registrantsSheet) {
    const firstPage = await page.request.get(`/api/v1/admin/events/${bts.id}/research/registrants?sheet=Registrants&page_size=1`)
    const firstRow = (await firstPage.json()).items[0]
    expect(firstRow).toBeTruthy()
    await expect(page.locator('.research-results-meta')).toContainText(`${registrantsSheet.row_count.toLocaleString()} rows in Registrants`)
    await page.getByRole('button', { name: 'Search across all worksheets' }).click()
    await page.getByPlaceholder(/Search Profile ID, name, company, title/).fill(firstRow.profile_id)
    const person = page.locator('.research-attendee-card').first()
    await expect(person).toContainText(firstRow.profile_id)
    await person.getByRole('button', { name: 'View profile' }).click()
    await expect(page.getByRole('dialog', { name: 'Research attendee profile' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Worksheet memberships' })).toBeVisible()
  }
})

test('event workspace shows explicit priorities, overdue follow-ups, and review queues', async ({ page }) => {
  const dueAt = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
  await page.route('**/priority-panels', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
    must_meet_next: { total: 2, priority_counts: { A: 1, B: 1 }, items: [
      { registrant_id: 'target-a', profile_id: 'PROFILE-A', full_name: 'Priority A Contact', company: 'Alpha Systems', sheet_name: 'Strong shortlist', priority: 'A', relationship: 'Client', fit: 'Strong', pitch: 'Review the A priority source note.' },
      { registrant_id: 'target-b', profile_id: 'PROFILE-B', full_name: 'Priority B Contact', company: 'Beta Systems', sheet_name: 'Strong shortlist', priority: 'B', relationship: 'Design Partner', fit: 'Strong' },
    ] },
    research_opportunities: { total: 1, items: [{ registrant_id: 'opportunity-1', profile_id: 'PROFILE-C', full_name: 'Partner Contact', company: 'Partner Systems', sheet_name: 'Design Partners', relationship: 'Design Partner', fit: 'Strong', pitch: 'Explore the source-backed partnership.' }] },
    follow_ups: { total: 1, items: [{ id: 'follow-up-1', kind: 'research_meeting', registrant_id: 'target-a', full_name: 'Priority A Contact', company: 'Alpha Systems', due_at: dueAt, status: 'requested', owner: 'Bhoomika', next_steps: 'Send the agenda.' }] },
    needs_review: { reconciliation_rows: 1, pending_card_captures: 1,
      reconciliation_items: [{ id: 'review-row-1', full_name: 'Review Contact', company: 'Review Systems', sheet_name: 'Strong shortlist', source_row: 12, errors: ['Missing Profile ID'] }],
      card_capture_items: [{ id: 'capture-1', status: 'pending_match', captured_at: dueAt, filename: 'visitor-card.jpg', name: 'Card Contact' }],
    },
  }) }))
  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  await page.goto('/admin/events')
  const bts = page.locator('.workspace-event-card').filter({ hasText: 'Bengaluru Tech Summit 2026' })
  await bts.getByRole('link', { name: 'Open workspace' }).click()
  const eventTabs = page.getByRole('navigation', { name: 'Event workspace' })
  await expect(eventTabs.getByRole('link')).toHaveCount(8)
  await expect(eventTabs.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByText('A 1 · B 1')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Must Meet Next' })).toBeVisible()
  await expect(page.locator('.event-priority-panel').filter({ has: page.getByRole('heading', { name: 'Must Meet Next' }) }).getByText('Priority A', { exact: true })).toBeVisible()
  await expect(page.locator('.event-priority-panel').filter({ has: page.getByRole('heading', { name: 'Must Meet Next' }) }).getByText('Priority B', { exact: true })).toBeVisible()
  await expect(page.getByText('Follow-up Today')).toBeVisible()
  await expect(page.getByText('Send the agenda.')).toBeVisible()
  await expect(page.getByText('Missing Profile ID')).toBeVisible()
  await expect(page.getByText('pending match')).toBeVisible()
  await eventTabs.getByRole('link', { name: 'Days & Sessions' }).click()
  await expect(page).toHaveURL(/#sessions$/)
  await expect(page.getByRole('heading', { name: 'Days & Sessions' })).toBeVisible()
  for (const width of [320, 375, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
})

test('research import preview shows checksum, identity coverage, warnings, and rollback state', async ({ page }) => {
  await page.route('**/api/v1/admin/events', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
    { id: 'quality-event', name: 'Quality Review Event', slug: 'quality-review', is_active: true },
  ]) }))
  await page.route('**/api/v1/admin/events/quality-event/research/imports', async route => {
    if (route.request().method() !== 'POST') return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({
      id: 'quality-preview', original_filename: 'research.xlsx', file_sha256: 'a'.repeat(64), status: 'preview',
      row_count: 5, sheet_names: ['Registrants', 'Strong shortlist'], error_count: 2,
      errors: [{ sheet_name: 'Strong shortlist', source_row: 5, message: 'Missing Profile ID' }],
      sheets: [
        { sheet_name: 'Registrants', columns: ['Profile ID', 'Name'], rows: 3, errors: 0 },
        { sheet_name: 'Strong shortlist', columns: ['Profile ID', 'Name'], rows: 2, errors: 2 },
      ],
      quality: { unique_profile_ids_in_registrants: 2, repeated_profile_ids_across_sheets: 1, missing_profile_id_rows: 1, warning_count: 2 },
      rollback_available: false, macros_executed: false,
    }) })
  })
  await page.route('**/api/v1/admin/events/quality-event/research/sheets', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ batch_id: null, original_filename: null, row_count: 0, sheets: [] }) }))
  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  await page.goto('/admin/research?eventId=quality-event')
  await page.locator('input[type=file]').setInputFiles({
    name: 'research.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('intercepted test workbook'),
  })
  await page.getByRole('button', { name: 'Preview workbook' }).click()
  await expect(page.getByRole('heading', { name: 'research.xlsx' })).toBeVisible()
  await expect(page.getByText('Source SHA-256')).toBeVisible()
  await expect(page.getByText('a'.repeat(64))).toBeVisible()
  await expect(page.getByText('Unique Profile IDs in Registrants')).toBeVisible()
  await expect(page.getByText('Repeated Profile IDs across worksheets')).toBeVisible()
  await expect(page.getByText('Rows missing Profile ID')).toBeVisible()
  await expect(page.getByText('preview · rollback unavailable until import')).toBeVisible()
  await expect(page.getByText(/Profile IDs are source identifiers and are not independently verified/)).toBeVisible()
})

test('research attendee supports meeting actions without creating a lead', async ({ page }) => {
  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bhoomika@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  const eventsResponse = page.waitForResponse(response => response.url().endsWith('/api/v1/admin/events') && response.ok())
  await page.goto('/admin/research')
  const events = await (await eventsResponse).json()
  const bts = events.find((event: { slug: string }) => event.slug === 'bts-2026')
  expect(bts).toBeTruthy()
  await page.getByRole('navigation', { name: 'Event workspace' }).getByRole('link', { name: 'Attendees' }).click()
  await expect(page).toHaveURL(/view=attendees/)
  await expect(page.getByRole('button', { name: 'Global search active' })).toBeVisible()
  const response = await page.request.get(`/api/v1/admin/events/${bts.id}/research/registrants?sheet=Registrants&page_size=1`)
  const firstRow = (await response.json()).items[0]
  expect(firstRow?.profile_id).toBeTruthy()
  const actions: Record<string, unknown>[] = []
  const createdEncounters: Record<string, unknown>[] = []
  const updates: Record<string, unknown>[] = []
  await page.route(`**/api/v1/admin/events/${bts.id}/research/attendees/*/encounters`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(createdEncounters) }))
  await page.route(`**/api/v1/admin/events/${bts.id}/encounters`, async route => {
    const payload = route.request().postDataJSON() as Record<string, unknown>
    actions.push(payload)
    const created = { id: `synthetic-${actions.length}`, event_id: bts.id, registrant_id: payload.registrant_id, lead_id: null, profile_id: firstRow.profile_id, full_name: firstRow.full_name, company: firstRow.company, employee_id: payload.employee_id, employee_name: 'Admin User', encounter_type: payload.encounter_type, status: payload.status, encountered_at: new Date().toISOString(), scheduled_at: payload.scheduled_at || null, topics: payload.topics || [], notes: payload.notes || '', demo_presented: payload.demo_presented || false, next_steps: payload.next_steps || '', follow_up_due_at: payload.follow_up_due_at || null, synthetic_test: true }
    createdEncounters.push(created)
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(created),
    })
  })
  await page.route('**/api/v1/admin/event-encounters/*', async route => {
    const id = route.request().url().split('/').pop() || ''
    const item = createdEncounters.find(encounter => encounter.id === id)
    const changes = route.request().postDataJSON() as Record<string, unknown>
    updates.push(changes)
    if (item) Object.assign(item, changes)
    await route.fulfill({ status: item ? 200 : 404, contentType: 'application/json', body: JSON.stringify(item || { detail: 'Event encounter not found.' }) })
  })
  await page.getByPlaceholder(/Search Profile ID, name, company, title/).fill(firstRow.profile_id)
  await page.locator('.research-attendee-card').first().getByRole('button', { name: 'View profile' }).click()
  for (const width of [320, 375, 390, 768]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.getByRole('button', { name: 'Mark Met' }).click()
  await expect(page.getByText('Event action recorded.')).toBeVisible()
  expect(actions[0]).toMatchObject({ registrant_id: firstRow.id, encounter_type: 'met', status: 'completed' })
  expect(actions[0]).not.toHaveProperty('lead_id')

  await page.getByRole('button', { name: 'Schedule Meeting' }).click()
  for (const width of [320, 375, 390, 768]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.getByLabel('Topics').fill('Agentic AI')
  await page.getByLabel('Notes').fill('Reviewed the research opportunity.')
  await page.getByLabel('Next steps').fill('Send the demo outline.')
  await page.getByLabel('Follow-up due').fill('2026-11-20')
  await page.getByRole('button', { name: 'Confirm meeting' }).click()
  await expect.poll(() => actions.length).toBe(2)
  expect(actions[1]).toMatchObject({ registrant_id: firstRow.id, encounter_type: 'meeting', status: 'confirmed', topics: ['Agentic AI'], notes: 'Reviewed the research opportunity.', next_steps: 'Send the demo outline.' })
  const meetingStatus = page.getByRole('combobox', { name: /Status for research meeting/ })
  await expect(meetingStatus).toHaveValue('confirmed')
  await meetingStatus.selectOption('completed')
  await expect.poll(() => updates.length).toBe(1)
  expect(updates[0]).toEqual({ status: 'completed' })
  await expect(meetingStatus).toHaveValue('completed')
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
  await expect(page.getByText(/requested · Bhoomika/).first()).toBeVisible()
  await expect(page.getByText('Share the demo deck.').first()).toBeVisible()
  const confirmMeeting = page.waitForResponse(response => response.request().method() === 'PATCH' && response.url().endsWith(`/api/v1/admin/meetings/${meeting.id}`) && response.status() === 200)
  await page.getByLabel(`Status for meeting ${meeting.id}`).selectOption('confirmed')
  await confirmMeeting
  await expect(page.getByText(/confirmed · Bhoomika/).first()).toBeVisible()
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

test('admin capture inbox filters by event and status and gives the next review action', async ({ page }) => {
  const requests: URLSearchParams[] = []
  await page.route('**/api/v1/admin/card-captures*', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/thumbnail')) return route.fulfill({ status: 404, body: '' })
    if (route.request().method() !== 'GET') return route.continue()
    requests.push(url.searchParams)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      total: 1,
      page: Number(url.searchParams.get('page') || '1'),
      page_size: 25,
      items: [{
        id: 'c46c5f49-21fd-4078-b82d-4c2edeb02015',
        event_id: 'bts-event',
        event_name: 'Bengaluru Tech Summit 2026',
        original_filename: 'visitor-card.jpg',
        status: 'pending_match',
        ocr: { full_name: 'Jhon Michai', company: 'Design Studio' },
        lead_name: null,
        lead_id: null,
        captured_by: 'Bhoomika',
        created_at: '2026-11-16T10:00:00+00:00',
        synthetic_test: false,
        candidates: [],
      }],
    }) })
  })
  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  await page.goto('/admin/card-capture')
  await expect(page.getByRole('heading', { name: 'Recent card captures' })).toBeVisible()
  await expect(page.getByText('Jhon Michai', { exact: true })).toBeVisible()
  await expect(page.getByText(/Bhoomika/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Resolve possible match' })).toBeVisible()

  await page.getByLabel('Filter captures by status').selectOption('pending_match')
  await expect.poll(() => requests.some(query => query.get('status') === 'pending_match')).toBe(true)
  const eventFilter = page.getByLabel('Filter captures by event')
  await eventFilter.selectOption({ label: 'Bengaluru Tech Summit 2026' })
  const selectedEventId = await eventFilter.inputValue()
  await expect.poll(() => requests.some(query => query.get('event_id') === selectedEventId)).toBe(true)
  await page.getByRole('checkbox', { name: 'Include synthetic tests' }).check()
  await expect.poll(() => requests.some(query => query.get('include_synthetic') === 'true')).toBe(true)
  await page.getByLabel('Filter captures by status').selectOption('new')
  await expect.poll(() => requests.some(query => Boolean(query.get('created_after')) && !query.get('status'))).toBe(true)
})

test('staff quick manual capture reviews matches and saves an event-attributed pending record', async ({ page }) => {
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/v1/admin/manual-captures', async route => {
    const payload = route.request().postDataJSON() as Record<string, unknown>
    requests.push(payload)
    if (requests.length === 1) {
      await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: {
        message: 'Possible matches need review. Link one record, or confirm this is a different visitor.',
        candidates: [{ kind: 'lead', id: 'existing-lead-1', full_name: 'Jamie Manual', company: 'Example Works', email: 'jamie@example.com', confidence: 'possible', matched_by: 'name_company' }],
      } }) })
      return
    }
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({
      lead_id: 'existing-lead-1', lead_code: 'LS-BTS-000001', lead_name: 'Jamie Manual', event_id: 'bts-event',
      event_name: 'Bengaluru Tech Summit 2026', status: 'pending_review', created_lead: false,
      matched_research: false, captured_by: 'Admin User', captured_at: new Date().toISOString(),
    }) })
  })
  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  await page.goto('/admin/card-capture')
  const quickCapture = page.locator('.quick-manual-capture')
  await quickCapture.locator('.quick-manual-form > label').first().locator('select').selectOption({ label: 'Bengaluru Tech Summit 2026' })
  await quickCapture.getByLabel('Name').fill('Jamie Manual')
  await quickCapture.getByLabel('Company').fill('Example Works')
  await quickCapture.getByLabel('Notes').fill('Asked about a product demo')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await quickCapture.getByRole('button', { name: 'Save quick capture' }).click()
  await expect(quickCapture.getByText(/Possible matches need review/)).toBeVisible()
  await quickCapture.locator('.quick-manual-candidate input').check()
  await quickCapture.getByRole('button', { name: 'Save quick capture' }).click()
  await expect(quickCapture.getByText('Event capture linked to existing lead')).toBeVisible()
  expect(requests).toHaveLength(2)
  expect(requests[0]).toMatchObject({ fields: { full_name: 'Jamie Manual', company: 'Example Works' }, notes: 'Asked about a product demo' })
  expect(requests[0]).not.toHaveProperty('data_processing_consent')
  expect(requests[1]).toMatchObject({ lead_id: 'existing-lead-1', event_id: expect.any(String) })
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
