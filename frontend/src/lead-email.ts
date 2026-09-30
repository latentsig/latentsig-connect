const personalEmailDomains = new Set([
  'gmail.com', 'googlemail.com', 'yahoo.com', 'yahoo.co.in', 'outlook.com',
  'hotmail.com', 'live.com', 'msn.com', 'icloud.com', 'me.com', 'aol.com',
  'proton.me', 'protonmail.com', 'gmx.com', 'mail.com', 'yandex.com', 'zoho.com',
])

export function inferEmailType(email: string): 'work' | 'personal' {
  const domain = email.trim().toLowerCase().split('@').at(-1) || ''
  return personalEmailDomains.has(domain) ? 'personal' : 'work'
}
