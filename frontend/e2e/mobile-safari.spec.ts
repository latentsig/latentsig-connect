import { expect, test } from '@playwright/test'

test('mobile Safari can record and confirm a lead meeting without horizontal overflow', async ({ page }) => {
  const suffix = Date.now()
  const contactName = `Mobile Safari ${suffix}`
  const created = await page.request.post('/api/v1/leads', {
    data: {
      full_name: contactName,
      company: 'Safari QA Example Ltd',
      job_title: 'Product Manager',
      email: `mobile-safari-${suffix}@example.com`,
      email_type: 'work',
      phone: '+919876543210',
      data_processing_consent: true,
      follow_up_consent: true,
      interest: ['AI Agents'],
      intent: 'I need a demo',
      event_slug: 'bts-2026',
      source: 'playwright-mobile-safari',
    },
  })
  expect(created.ok()).toBeTruthy()
  const lead = await created.json()

  await page.goto('/admin/login')
  await page.getByPlaceholder('name@latentsig.com').fill('bharat@latentsig.com')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/admin\/dashboard$/)
  await page.goto('/admin/leads')
  await page.getByPlaceholder('Search name, company, email or phone').fill(contactName)
  await page.getByRole('link', { name: new RegExp(contactName) }).first().click()

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByLabel('Meeting date and time').fill('2026-11-18T10:30')
  await page.getByLabel('Meeting status').selectOption('requested')
  await page.getByLabel('Topics').fill('Agentic AI')
  await page.getByLabel('Next steps').fill('Send the demo deck.')
  const meetingResponse = page.waitForResponse(response => response.request().method() === 'POST'
    && response.url() === `http://localhost:5173/api/v1/admin/leads/${lead.id}/meetings`
    && response.status() === 201)
  await page.getByRole('button', { name: 'Record meeting' }).click()
  const meeting = await (await meetingResponse).json()
  await expect(page.getByText(/requested ·/)).toBeVisible()

  const confirmResponse = page.waitForResponse(response => response.request().method() === 'PATCH'
    && response.url().endsWith(`/api/v1/admin/meetings/${meeting.id}`)
    && response.status() === 200)
  await page.getByLabel(`Status for meeting ${meeting.id}`).selectOption('confirmed')
  await confirmResponse
  await expect(page.getByText(/confirmed ·/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
