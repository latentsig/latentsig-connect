type EmailType = 'work' | 'personal'

export function EmailTypeControl({ value, onChange }: { value: EmailType; onChange: (value: EmailType) => void }) {
  return <div className="email-kind" role="group" aria-label="Email address type">
    <span className="email-kind-label">This is my</span>
    <label><input type="radio" name="email_type" value="work" checked={value === 'work'} onChange={() => onChange('work')}/> Work</label>
    <label><input type="radio" name="email_type" value="personal" checked={value === 'personal'} onChange={() => onChange('personal')}/> Personal</label>
  </div>
}
