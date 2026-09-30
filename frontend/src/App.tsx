import { forwardRef, useRef, useState } from 'react'
import { Link, Route, Routes, useNavigate, useSearchParams } from 'react-router-dom'
import { Controller, useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import PhoneInput, { isValidPhoneNumber } from 'react-phone-number-input'
import 'react-phone-number-input/style.css'
import { ArrowLeft, ArrowRight, ArrowUpRight, Check, ChevronRight, LockKeyhole, ScanLine, ShieldCheck, Upload, UserRound } from 'lucide-react'
import Admin from './Admin'
import { EmailTypeControl } from './EmailTypeControl'
import { inferEmailType } from './lead-email'

const configuredApiBase = import.meta.env.VITE_API_BASE_URL || ''
const apiBase = configuredApiBase === '__LATENTSIG_LOCAL_API__'
  ? `${window.location.protocol}//${window.location.hostname}:8000`
  : configuredApiBase
const interests = ['AI Agents', 'Data & Analytics', 'Automation', 'Software Development', 'QA / Testing', 'Product Development', 'Partnership', 'Other']
const intents = ['I have a project', 'I need a demo', 'I am looking for a technology partner', 'Partnership opportunity', 'Investment / business discussion', 'I want to explore LatentSig services', 'Just connecting', 'Other']

const leadSchema = z.object({
  full_name: z.string().trim().min(2, 'Please enter your full name.'),
  company: z.string().trim().min(1, 'Please enter your company.'),
  job_title: z.string().trim().min(1, 'Please enter your role.'),
  email: z.email('Enter a valid email address.'),
  phone: z.string().refine((value) => Boolean(value) && isValidPhoneNumber(value), 'Choose a country and enter a valid phone number.'),
  email_type: z.enum(['work', 'personal']),
  website: z.string().optional(),
  country: z.string().optional(),
  interest: z.array(z.string()).min(1, 'Choose at least one area of interest.'),
  intent: z.string().min(1, 'Choose what you would like to discuss.'),
  other_interest_details: z.string().max(100, 'Keep this answer brief.'),
  other_intent_details: z.string().max(100, 'Keep this answer brief.'),
  requirement_message: z.string().max(1000, 'Keep your message under 1,000 characters.').optional(),
}).superRefine((values, context) => {
  const validations = [
    [values.interest.includes('Other'), values.other_interest_details, 'other_interest_details', 'Please explain your interest in 5 words or fewer.'],
    [values.intent === 'Other', values.other_intent_details, 'other_intent_details', 'Please explain what you would like to discuss in 5 words or fewer.'],
  ] as const
  for (const [selected, answer, path, requiredMessage] of validations) {
    if (!selected) continue
    const trimmed = answer.trim()
    if (!trimmed) context.addIssue({ code: 'custom', path: [path], message: requiredMessage })
    else if (trimmed.split(/\s+/).length > 5) context.addIssue({ code: 'custom', path: [path], message: 'Keep your explanation to 5 words or fewer.' })
  }
})
type LeadForm = z.infer<typeof leadSchema>
const emptyLead: LeadForm = { full_name: '', company: '', job_title: '', email: '', email_type: 'work', phone: '', website: '', country: '', interest: [], intent: '', other_interest_details: '', other_intent_details: '', requirement_message: '' }

const PhoneNumberInput = forwardRef<HTMLInputElement, React.ComponentProps<'input'>>((props, ref) => {
  const { onChange, onBeforeInput, ...rest } = props
  return <input {...rest} ref={ref} type="tel" inputMode="tel" pattern="[+0-9 ()-]*" onBeforeInput={(event) => {
    const inputEvent = event.nativeEvent as InputEvent
    if (inputEvent.data && /[^0-9+ ()-]/.test(inputEvent.data)) event.preventDefault()
    onBeforeInput?.(event)
  }} onChange={(event) => {
    const input = event.currentTarget
    const clean = input.value.replace(/[^0-9+ ()-]/g, '')
    if (clean !== input.value) {
      const start = input.selectionStart
      const removedBeforeCursor = input.value.slice(0, start ?? input.value.length).replace(/[0-9+ ()-]/g, '').length
      input.value = clean
      const cursor = Math.max(0, (start ?? clean.length) - removedBeforeCursor)
      input.setSelectionRange(cursor, cursor)
    }
    onChange?.(event)
  }} />
})
PhoneNumberInput.displayName = 'PhoneNumberInput'

function Brand() { return <Link to="/connect" className="brand" aria-label="LatentSig Connect home"><img src="/logo.png" alt="LatentSig" /></Link> }
function Header() { return <header className="topbar"><Brand /><span className="secure-label"><LockKeyhole size={14} /> Private & secure</span></header> }
function PageFrame({ children, compact = false }: { children: React.ReactNode, compact?: boolean }) { return <div className="app-shell"><Header /><main className={compact ? 'page-content compact' : 'page-content'}>{children}</main><footer className="footer"><span>© 2026 LatentSig</span><span><ShieldCheck size={14} /> Your details stay with our team</span></footer></div> }

function Home() {
  const [params] = useSearchParams()
  const preserve = params.toString()
  return <PageFrame><section className="hero"><div className="eyebrow"><span className="live-dot" /> LATENTSIG CONNECT</div><h1>Let’s stay<br className="mobile-break" /> connected<span className="period">.</span></h1><p className="hero-copy">Met our team today? Share your details in less than a minute.</p>
    <div className="choice-grid">
      <Link to={`/connect/card${preserve ? `?${preserve}` : ''}`} className="choice-card card-choice"><span className="choice-icon scan-icon"><ScanLine size={23} /></span><span className="choice-text"><strong>Scan / Upload Business Card</strong><small>Fastest option</small></span><ArrowUpRight className="choice-arrow" size={19} /></Link>
      <Link to={`/connect/manual${preserve ? `?${preserve}` : ''}`} className="choice-card"><span className="choice-icon manual-icon"><UserRound size={23} /></span><span className="choice-text"><strong>Enter Details Manually</strong><small>Takes less than a minute</small></span><ArrowUpRight className="choice-arrow" size={19} /></Link>
    </div>
    <div className="privacy-note"><LockKeyhole size={15} /><span>Your information is securely shared only with the LatentSig team.</span></div>
  </section></PageFrame>
}

function Field({ label, name, type = 'text', placeholder, register, error, autoComplete }: { label: string; name: keyof LeadForm; type?: string; placeholder: string; register: ReturnType<typeof useForm<LeadForm>>['register']; error?: string; autoComplete?: string }) {
  return <label className="field"><span>{label}</span><input type={type} placeholder={placeholder} autoComplete={autoComplete} {...register(name)} aria-invalid={Boolean(error)} />{error && <small className="field-error">{error}</small>}</label>
}

function LeadFormPage({ initialValues, captureMethod = 'manual' }: { initialValues?: Partial<LeadForm>; captureMethod?: 'manual' | 'business_card' }) {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { register, control, handleSubmit, watch, setValue, formState: { errors, isSubmitting } } = useForm<LeadForm>({ resolver: zodResolver(leadSchema), defaultValues: { ...emptyLead, ...initialValues } })
  const chosen = watch('interest') || []
  const otherInterestSelected = chosen.includes('Other')
  const otherIntentSelected = watch('intent') === 'Other'
  const [apiError, setApiError] = useState('')
  const submit = handleSubmit(async (values) => {
    setApiError('')
    try {
      const cardDraft = captureMethod === 'business_card' ? JSON.parse(sessionStorage.getItem('latentsig-card-draft') || '{}') as Record<string, unknown> : {}
      const tokens = cardDraft.business_card_tokens as { front?: string; back?: string } | undefined
      const response = await fetch(`${apiBase}/api/v1/leads`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...values, capture_method: captureMethod, source: params.get('ref') || 'direct', event_slug: params.get('event') || undefined, utm_source: params.get('utm_source'), utm_medium: params.get('utm_medium'), utm_campaign: params.get('utm_campaign'), business_card_token: tokens?.front || cardDraft.business_card_token, business_card_back_token: tokens?.back, business_card_ocr: captureMethod === 'business_card' ? cardDraft : undefined }) })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({})) as { detail?: string }
        throw new Error(response.status === 429 ? 'Please wait a moment before trying again.' : payload.detail || 'We couldn’t submit your details. Please try again.')
      }
      sessionStorage.setItem('latentsig-thanks-name', values.full_name.split(/\s+/)[0])
      if (captureMethod === 'business_card') sessionStorage.removeItem('latentsig-card-draft')
      navigate('/connect/thank-you')
    } catch (error) {
      setApiError(error instanceof TypeError
        ? 'Could not reach the local LatentSig API at localhost:8000. Start the backend using the README instructions, then submit again. Your details have not been sent.'
        : error instanceof Error ? error.message : 'We couldn’t submit your details. Please try again.')
    }
  })
  const toggleInterest = (item: string) => setValue('interest', chosen.includes(item) ? chosen.filter((x) => x !== item) : [...chosen, item], { shouldValidate: true })
  return <PageFrame compact><Link to={captureMethod === 'business_card' ? '/connect/card' : `/connect${params.toString() ? `?${params}` : ''}`} className="back-link"><ArrowLeft size={16} /> Back</Link><div className="form-heading"><div className="step-label">{captureMethod === 'business_card' ? '02' : '01'} <span /> {captureMethod === 'business_card' ? 'CHECK YOUR DETAILS' : 'YOUR DETAILS'}</div><h1>{captureMethod === 'business_card' ? <>Please confirm<br className="mobile-break"/> your details.</> : <>Tell us a little<br className="mobile-break"/> about yourself.</>}</h1><p>{captureMethod === 'business_card' ? 'We’ve filled in what we could. Edit anything that needs a correction.' : 'Just the essentials. This takes about a minute.'}</p></div>
    <form onSubmit={submit} noValidate>
      <div className="form-section"><div className="section-title"><span className="section-number">01</span><div><h2>Contact details</h2><p>How can our team reach you?</p></div></div>
        <div className="fields-grid"><Field label="Full name" name="full_name" placeholder="e.g. Rachel Thomas" register={register} error={errors.full_name?.message} autoComplete="name"/><Field label="Company" name="company" placeholder="e.g. ABC Technologies" register={register} error={errors.company?.message} autoComplete="organization"/><Field label="Job title / designation" name="job_title" placeholder="e.g. VP Innovation" register={register} error={errors.job_title?.message} autoComplete="organization-title"/><div className="field"><span>Email address <em>*</em></span><input type="email" placeholder="you@company.com" autoComplete="email" {...register('email', { onChange: (event) => setValue('email_type', inferEmailType(event.target.value)) })} aria-invalid={Boolean(errors.email)}/><EmailTypeControl value={watch('email_type')} onChange={value=>setValue('email_type',value)}/>{errors.email?.message && <small className="field-error">{errors.email.message}</small>}</div><label className="field"><span>WhatsApp / phone <em>*</em></span><Controller name="phone" control={control} render={({ field }) => <PhoneInput international defaultCountry="IN" countryCallingCodeEditable={false} value={field.value || undefined} onChange={(value) => field.onChange(value || '')} onBlur={field.onBlur} name={field.name} autoComplete="tel" inputComponent={PhoneNumberInput} placeholder="Enter phone number"/>}/>{errors.phone?.message && <small className="field-error">{errors.phone.message}</small>}<small className="field-hint">Choose your country; its calling code is added automatically.</small></label><Field label="Company website" name="website" type="url" placeholder="https://company.com" register={register} error={errors.website?.message} autoComplete="url"/></div>
      </div>
      <div className="form-section"><div className="section-title"><span className="section-number">02</span><div><h2>What brings you here?</h2><p>Select everything that sounds relevant.</p></div></div><div className="field"><span>What are you interested in? <em>*</em></span><div className="chip-group">{interests.map((item) => <button type="button" key={item} className={`interest-chip ${chosen.includes(item) ? 'selected' : ''}`} aria-pressed={chosen.includes(item)} onClick={() => toggleInterest(item)}>{chosen.includes(item) && <Check size={14}/ >}{item}</button>)}</div>{errors.interest?.message && <small className="field-error">{errors.interest.message}</small>}</div>
        {otherInterestSelected && <label className="field message-field"><span>What are you interested in? Explain in 5 words <em>*</em></span><textarea rows={2} maxLength={100} placeholder="e.g. RAG agent" aria-invalid={Boolean(errors.other_interest_details)} {...register('other_interest_details')} />{errors.other_interest_details?.message && <small className="field-error">{errors.other_interest_details.message}</small>}<small className="helper">{(watch('other_interest_details') || '').trim() ? (watch('other_interest_details') || '').trim().split(/\s+/).length : 0} / 5 words</small></label>}
        <label className="field intent-field"><span>What would you like to discuss? <em>*</em></span><select {...register('intent')} aria-invalid={Boolean(errors.intent)}><option value="">Choose an option</option>{intents.map((intent) => <option key={intent}>{intent}</option>)}</select>{errors.intent?.message && <small className="field-error">{errors.intent.message}</small>}</label>
        {otherIntentSelected && <label className="field message-field"><span>What would you like to discuss? Explain in 5 words <em>*</em></span><textarea rows={2} maxLength={100} placeholder="e.g. RAG agent" aria-invalid={Boolean(errors.other_intent_details)} {...register('other_intent_details')} />{errors.other_intent_details?.message && <small className="field-error">{errors.other_intent_details.message}</small>}<small className="helper">{(watch('other_intent_details') || '').trim() ? (watch('other_intent_details') || '').trim().split(/\s+/).length : 0} / 5 words</small></label>}
        {(otherInterestSelected || otherIntentSelected) && <label className="field message-field"><span>How did you feel? What could we improve? <small className="optional">OPTIONAL</small></span><textarea rows={3} maxLength={1000} placeholder="Share your thoughts with us" aria-invalid={Boolean(errors.requirement_message)} {...register('requirement_message')} />{errors.requirement_message?.message && <small className="field-error">{errors.requirement_message.message}</small>}<small className="helper">{(watch('requirement_message') || '').length} / 1,000</small></label>}
        {!otherInterestSelected && !otherIntentSelected && <label className="field message-field"><span>Tell us briefly what you are looking for <small className="optional">OPTIONAL</small></span><textarea rows={3} maxLength={1000} placeholder="A sentence or two is perfect" aria-invalid={Boolean(errors.requirement_message)} {...register('requirement_message')} /><small className="helper">{(watch('requirement_message') || '').length} / 1,000</small></label>}
      </div>
      <div className="submit-wrap">{apiError && <div className="api-error" role="alert">{apiError}</div>}<button className="primary-button" disabled={isSubmitting}>{isSubmitting ? 'Sending…' : 'Connect with LatentSig'}<ArrowRight size={18}/></button><p className="consent"><LockKeyhole size={13}/> By continuing, you agree LatentSig may contact you about your enquiry.</p></div>
    </form>
  </PageFrame>
}

function CardUpload() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const query = params.toString()
  const withAttribution = (path: string) => `${path}${query ? `?${query}` : ''}`
  const [frontFile, setFrontFile] = useState<File | null>(null)
  const [backFile, setBackFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const cameraInput = useRef<HTMLInputElement>(null)
  const uploadInput = useRef<HTMLInputElement>(null)
  const backCameraInput = useRef<HTMLInputElement>(null)
  const backUploadInput = useRef<HTMLInputElement>(null)

  async function upload() {
    if (!frontFile) { setError('Choose a photo of the front of your business card to continue.'); return }
    const selected = [frontFile, backFile].filter((item): item is File => Boolean(item))
    if (selected.some((item) => !['image/jpeg', 'image/png', 'image/webp'].includes(item.type) || item.size > 10 * 1024 * 1024)) { setError('Use JPG, PNG or WEBP images under 10 MB each.'); return }
    setBusy(true); setError('')
    try {
      const body = new FormData(); selected.forEach((item) => body.append('files', item))
      const response = await fetch(`${apiBase}/api/v1/ocr/business-card`, { method: 'POST', body })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({})) as { detail?: string }
        throw new Error(payload.detail || 'Local card scanning could not read this image. You can enter your details manually instead.')
      }
      const result = await response.json(); sessionStorage.setItem('latentsig-card-draft', JSON.stringify(result)); navigate(withAttribution('/connect/card/review'))
    } catch (e) {
      setError(e instanceof TypeError
        ? 'Could not reach the local OCR server. Start the FastAPI backend on port 8000, then try again. Your photo has not been sent to an OCR service.'
        : e instanceof Error ? e.message : 'Could not read that image.')
    } finally { setBusy(false) }
  }

  const onFile = (side: 'front' | 'back') => (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] || null
    if (side === 'front') setFrontFile(selected); else setBackFile(selected)
    event.target.value = ''
    setError('')
  }

  return <PageFrame compact>
    <Link to={withAttribution('/connect')} className="back-link"><ArrowLeft size={16}/> Back</Link>
    <div className="form-heading"><div className="step-label">01 <span/> BUSINESS CARD</div><h1>Let your card<br className="mobile-break"/> do the talking.</h1><p>We?ll pick out your details for you to review before sharing.</p></div>
    <div className="upload-panel">
      <div className="upload-art"><div className="art-orbit orbit-one"/><div className="art-orbit orbit-two"/><div className="card-illustration"><span/><span/><span/><i/></div><div className="spark spark-one">?</div><div className="spark spark-two">?</div></div>
      <div className="upload-prompt"><strong>Take a photo of your business card</strong><span>Upload the front and, if available, the back. We’ll read both together.</span></div>
      <input ref={cameraInput} className="file-input" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={onFile('front')}/>
      <input ref={uploadInput} className="file-input" type="file" accept="image/jpeg,image/png,image/webp" onChange={onFile('front')}/>
      <input ref={backCameraInput} className="file-input" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={onFile('back')}/>
      <input ref={backUploadInput} className="file-input" type="file" accept="image/jpeg,image/png,image/webp" onChange={onFile('back')}/>
      <div className="card-side"><b>Front of card <em>*</em></b>{frontFile ? <div className="selected-file"><span>{frontFile.name}</span><button type="button" onClick={() => {setFrontFile(null);setError('')}}>Remove</button></div> : <div className="card-upload-actions"><button type="button" className="primary-button" onClick={() => cameraInput.current?.click()}><ScanLine size={18}/> Take Photo</button><button type="button" className="upload-secondary" onClick={() => uploadInput.current?.click()}><Upload size={17}/> Upload Image</button></div>}</div>
      <div className="card-side"><b>Back of card <small>OPTIONAL</small></b>{backFile ? <div className="selected-file"><span>{backFile.name}</span><button type="button" onClick={() => {setBackFile(null);setError('')}}>Remove</button></div> : <div className="card-upload-actions"><button type="button" className="upload-secondary" onClick={() => backCameraInput.current?.click()}><ScanLine size={18}/> Take Photo</button><button type="button" className="upload-secondary" onClick={() => backUploadInput.current?.click()}><Upload size={17}/> Upload Image</button></div>}</div>
      <small className="upload-format">JPG, PNG, WEBP · max 10 MB per side</small>
      {error && <div className="api-error" role="alert">{error}</div>}
      {frontFile && <button className="primary-button scan-submit" onClick={upload} disabled={busy}>{busy ? 'Reading your card…' : 'Scan business card'}<ArrowRight size={18}/></button>}
      <button className="text-button" onClick={() => navigate(withAttribution('/connect/manual'))}>I?ll enter my details instead <ChevronRight size={16}/></button>
    </div>
    <p className="secure-caption"><LockKeyhole size={14}/> OCR runs on LatentSig?s server; card images are not sent to third-party OCR services.</p>
  </PageFrame>
}

function CardReview() {
  const draft = JSON.parse(sessionStorage.getItem('latentsig-card-draft') || '{}') as Record<string, {value?: string}>
  const fields = [['Full name','full_name'],['Company','company'],['Job title','job_title'],['Email address','email'],['Phone','phone'],['Website','website']]
  return <LeadFormPage key="review-form" captureMethod="business_card" initialValues={{ ...Object.fromEntries(fields.map(([, key]) => [key, draft[key]?.value || ''])), email_type: draft.email_type?.value === 'personal' ? 'personal' : 'work' }}/>
}

function ThankYou() { const first = sessionStorage.getItem('latentsig-thanks-name') || 'there'; const number = import.meta.env.VITE_WHATSAPP_NUMBER || ''; const href = `https://wa.me/${number}?text=${encodeURIComponent('Hi LatentSig,\n\nI just connected with your team and I’d like to continue our discussion.')}`; return <PageFrame><section className="thanks-panel"><div className="success-mark"><Check size={28}/></div><div className="eyebrow">CONNECTION MADE</div><h1>Thank you,<br/>{first}<span className="period">.</span></h1><p>It was great connecting with you.<br/>Our team will follow up shortly.</p><a className="primary-button anchor-button" href={href} target="_blank" rel="noreferrer">Continue on WhatsApp <ArrowUpRight size={18}/></a><a href="https://latentsig.com" className="visit-link">Visit LatentSig <ArrowRight size={15}/></a></section></PageFrame> }

function App() { return <Routes><Route path="/" element={<Home/>}/><Route path="/connect" element={<Home/>}/><Route path="/connect/manual" element={<LeadFormPage/>}/><Route path="/connect/card" element={<CardUpload/>}/><Route path="/connect/card/review" element={<CardReview/>}/><Route path="/connect/thank-you" element={<ThankYou/>}/><Route path="/admin/*" element={<Admin/>}/><Route path="*" element={<Home/>}/></Routes> }
export default App
