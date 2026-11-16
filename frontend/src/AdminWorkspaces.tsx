import { useEffect, useState } from 'react'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, FileSpreadsheet, Search, ShieldCheck, Upload } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import './admin-workspaces.css'

const configuredApiBase = import.meta.env.VITE_API_BASE_URL || ''
const apiBase = configuredApiBase === '__LATENTSIG_LOCAL_API__' ? `${window.location.protocol}//${window.location.hostname}:8000` : configuredApiBase

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (typeof init?.body === 'string' && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${apiBase}${path}`, { ...init, headers, credentials: 'include' })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string | Record<string, unknown> }
    throw new Error(typeof body.detail === 'string' ? body.detail : body.detail ? JSON.stringify(body.detail) : `Request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

type EventRow = { id: string; name: string; slug: string; start_date?: string; end_date?: string; location?: string; venue?: string; is_active: boolean; profile_id?: string }
type SessionRow = { id: string; name: string; slug: string; starts_at?: string; ends_at?: string; venue?: string; is_active: boolean }
type PriorityTarget = { registrant_id: string; profile_id?: string; full_name?: string; company?: string; job_title?: string; sheet_name: string; priority?: string; relationship?: string; fit?: string; pitch?: string }
type EventFollowUp = { id: string; kind: string; lead_id?: string; registrant_id?: string; full_name?: string; company?: string; due_at: string; next_steps?: string; status: string; owner?: string }
type EventPriorityPanels = { must_meet_next: { total: number; priority_counts: { A: number; B: number }; items: PriorityTarget[] }; research_opportunities: { total: number; items: PriorityTarget[] }; follow_ups: { total: number; items: EventFollowUp[] }; needs_review: { reconciliation_rows: number; pending_card_captures: number; reconciliation_items: { id: string; full_name?: string; company?: string; sheet_name: string; source_row: number; errors: string[] }[]; card_capture_items: { id: string; status: string; captured_at: string; filename: string; name?: string }[] } }
type EventMeeting = { id: string; kind: 'lead_meeting' | 'research_meeting'; lead_id?: string; registrant_id?: string; full_name?: string; company?: string; session_name?: string; scheduled_at?: string; employee_id?: string; employee_name?: string; topics: string[]; notes?: string; status: string; next_steps?: string; follow_up_due_at?: string; demo_presented: boolean }
type ProfileRow = { id: string; name: string; location?: string; venue?: string; sessions_template: { name: string; venue?: string; starts_at?: string; ends_at?: string }[] }
type Person = { id: string; full_name: string; email: string; role: string; is_active?: boolean }
const dateLabel = (value?: string) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(`${value.slice(0, 10)}T12:00:00`)) : 'Date not set'

function SectionTitle({ kicker, title, children }: { kicker: string; title: string; children?: React.ReactNode }) {
  return <div className="admin-page-title"><div><span className="admin-kicker">{kicker}</span><h1>{title}</h1></div>{children}</div>
}

function EventQR({ event, session }: { event: EventRow; session?: SessionRow }) {
  const [open, setOpen] = useState(false)
  const base = import.meta.env.VITE_PUBLIC_SITE_URL || window.location.origin
  const url = new URL('/connect', base)
  url.searchParams.set('event', event.slug)
  if (session) url.searchParams.set('session', session.slug)
  url.searchParams.set('ref', 'booth')
  url.searchParams.set('utm_source', 'latentsig')
  url.searchParams.set('utm_medium', 'qr')
  url.searchParams.set('utm_campaign', event.slug)
  const id = `${event.slug}-${session?.slug || 'event'}`
  function download() {
    const svg = document.querySelector(`[data-event-qr="${id}"] svg`)
    if (!svg) return
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([svg.outerHTML], { type: 'image/svg+xml' }))
    link.download = `${id}-capture-qr.svg`
    link.click()
    URL.revokeObjectURL(link.href)
  }
  return <div className="workspace-qr"><button type="button" className="workspace-link-button" onClick={() => setOpen(!open)}>{open ? 'Hide QR' : 'Show QR'}</button>{open && <div className="workspace-qr-panel"><div data-event-qr={id}><QRCodeSVG value={url.toString()} size={156} level="M" title={`${event.name}${session ? ` — ${session.name}` : ''} QR`}/></div><a href={url.toString()} target="_blank" rel="noreferrer">Open capture link</a><button type="button" className="workspace-link-button" onClick={download}>Download QR image</button></div>}</div>
}

function EventTabNavigation({ eventId, active }: { eventId: string; active: string }) {
  const tabs = [
    { key: 'overview', label: 'Overview', to: `/admin/events/${eventId}` },
    { key: 'attendees', label: 'Attendees', to: `/admin/research?eventId=${eventId}&view=attendees` },
    { key: 'research', label: 'Research', to: `/admin/research?eventId=${eventId}&view=research` },
    { key: 'captures', label: 'Card Captures', to: `/admin/card-capture?eventId=${eventId}` },
    { key: 'meetings', label: 'Meetings', to: `/admin/events/${eventId}#meetings` },
    { key: 'follow-ups', label: 'Follow-ups', to: `/admin/events/${eventId}#follow-ups` },
    { key: 'sessions', label: 'Days & Sessions', to: `/admin/events/${eventId}#sessions` },
    { key: 'imports', label: 'Imports & Reports', to: `/admin/research?eventId=${eventId}&view=imports#research-imports` },
  ]
  return <nav className="event-workspace-tabs" aria-label="Event workspace">
    {tabs.map(tab => <Link key={tab.key} to={tab.to} className={active === tab.key ? 'event-workspace-tab active' : 'event-workspace-tab'} aria-current={active === tab.key ? 'page' : undefined}>{tab.label}</Link>)}
  </nav>
}

export function EventWorkspaces() {
  const client = useQueryClient()
  const actor = useQuery({ queryKey: ['admin-me'], queryFn: () => api<Person>('/api/v1/auth/me') })
  const events = useQuery({ queryKey: ['events'], queryFn: () => api<EventRow[]>('/api/v1/admin/events') })
  const profiles = useQuery({ queryKey: ['event-profiles'], queryFn: () => api<ProfileRow[]>('/api/v1/admin/event-profiles') })
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [profileId, setProfileId] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [location, setLocation] = useState('')
  const [venue, setVenue] = useState('')
  const [message, setMessage] = useState('')
  useEffect(() => { if (name && !slug) setSlug(name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')) }, [name, slug])
  const createEvent = useMutation({
    mutationFn: () => profileId
      ? api('/api/v1/admin/events/from-profile', { method: 'POST', body: JSON.stringify({ profile_id: profileId, name, slug, start_date: startDate || null, end_date: endDate || null }) })
      : api('/api/v1/admin/events', { method: 'POST', body: JSON.stringify({ name, slug, start_date: startDate || null, end_date: endDate || null, location: location || null, venue: venue || null, is_active: true }) }),
    onSuccess: () => { setName(''); setSlug(''); setProfileId(''); setStartDate(''); setEndDate(''); setLocation(''); setVenue(''); setMessage('Event workspace created.'); void client.invalidateQueries({ queryKey: ['events'] }) },
    onError: error => setMessage(error.message),
  })
  return <>
    <SectionTitle kicker="EVENT WORKSPACES" title="Events"><Link to="/admin/card-capture" className="admin-action">Scan &amp; Save Business Card <Upload size={15}/></Link></SectionTitle>
    {events.isError && <div className="admin-error">{(events.error as Error).message}</div>}
    <div className="workspace-event-grid">{events.data?.map(event => <article className="workspace-event-card" key={event.id}>
      <div className="workspace-event-heading"><span className="workspace-icon"><CalendarDays size={18}/></span><span className={event.is_active ? 'event-state active' : 'event-state'}>{event.is_active ? 'Active' : 'Inactive'}</span></div>
      <h2>{event.name}</h2><p>{dateLabel(event.start_date)}{event.end_date && event.end_date !== event.start_date ? ` – ${dateLabel(event.end_date)}` : ''}</p>
      <p>{[event.venue, event.location].filter(Boolean).join(' · ') || 'Venue not set'}</p>
      <div className="workspace-event-actions"><Link className="admin-action" to={`/admin/events/${event.id}`}>Open workspace</Link><EventQR event={event}/></div>
    </article>)}</div>
    {['ADMIN', 'MANAGER'].includes(actor.data?.role || '') && <section className="workspace-form-card"><span className="admin-kicker">SETUP</span><h2>Create an event workspace</h2><p>Start from a saved profile to reuse venue and session details.</p>
      <form className="workspace-form-grid" onSubmit={event => { event.preventDefault(); setMessage(''); createEvent.mutate() }}>
        <label>Event name<input required value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Bengaluru Tech Summit 2026"/></label>
        <label>Capture link slug<input required value={slug} onChange={e => setSlug(e.target.value)} pattern="[a-z0-9]+(?:-[a-z0-9]+)*" placeholder="bts-2026"/></label>
        <label>Start date<input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}/></label>
        <label>End date<input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}/></label>
        {!profileId && <><label>City / location<input value={location} onChange={e => setLocation(e.target.value)} placeholder="Bengaluru"/></label><label>Venue<input value={venue} onChange={e => setVenue(e.target.value)} placeholder="Venue name"/></label></>}
        <label className="wide-field">Reusable profile<select value={profileId} onChange={e => setProfileId(e.target.value)}><option value="">No profile</option>{profiles.data?.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
        <button className="admin-primary wide-field" disabled={createEvent.isPending}>Create workspace</button>
      </form>{message && <p className={createEvent.isError ? 'workspace-error' : 'workspace-success'} role="status">{message}</p>}
    </section>}
  </>
}

export function EventDashboard() {
  const { eventId = '' } = useParams()
  const location = useLocation()
  const client = useQueryClient()
  const eventQuery = useQuery({ queryKey: ['events'], queryFn: () => api<EventRow[]>('/api/v1/admin/events') })
  const actor = useQuery({ queryKey: ['admin-me'], queryFn: () => api<Person>('/api/v1/auth/me') })
  const events = eventQuery.data || []
  const event = events.find(item => item.id === eventId)
  const metrics = useQuery({ queryKey: ['event-dashboard', eventId], queryFn: () => api<any>(`/api/v1/admin/events/${eventId}/dashboard`), enabled: Boolean(eventId) })
  const priorityPanels = useQuery({ queryKey: ['event-priority-panels', eventId], queryFn: () => api<EventPriorityPanels>(`/api/v1/admin/events/${eventId}/priority-panels`), enabled: Boolean(eventId) })
  const eventMeetings = useQuery({ queryKey: ['event-meetings', eventId], queryFn: () => api<EventMeeting[]>(`/api/v1/admin/events/${eventId}/meetings`), enabled: Boolean(eventId) })
  const sessions = useQuery({ queryKey: ['event-sessions', eventId], queryFn: () => api<SessionRow[]>(`/api/v1/admin/events/${eventId}/sessions`), enabled: Boolean(eventId) })
  const canManage = ['ADMIN', 'MANAGER'].includes(actor.data?.role || '')
  const team = useQuery({ queryKey: ['team'], queryFn: () => api<Person[]>('/api/v1/admin/team'), enabled: canManage })
  const staff = useQuery({ queryKey: ['event-staff', eventId], queryFn: () => api<{ user_id: string }[]>(`/api/v1/admin/events/${eventId}/staff`), enabled: Boolean(eventId) })
  const [assignedIds, setAssignedIds] = useState<string[]>([])
  const [sessionName, setSessionName] = useState('')
  const [sessionSlug, setSessionSlug] = useState('')
  const [sessionVenue, setSessionVenue] = useState('')
  const [startsAt, setStartsAt] = useState('')
  const [endsAt, setEndsAt] = useState('')
  const [notice, setNotice] = useState('')
  const [profileName, setProfileName] = useState('')
  useEffect(() => { if (staff.data) setAssignedIds(staff.data.map(item => item.user_id)) }, [staff.data])
  useEffect(() => { if (sessionName && !sessionSlug) setSessionSlug(sessionName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')) }, [sessionName, sessionSlug])
  const addSession = useMutation({ mutationFn: () => api(`/api/v1/admin/events/${eventId}/sessions`, { method: 'POST', body: JSON.stringify({ name: sessionName, slug: sessionSlug, venue: sessionVenue || null, starts_at: startsAt ? new Date(startsAt).toISOString() : null, ends_at: endsAt ? new Date(endsAt).toISOString() : null }) }), onSuccess: () => { setSessionName(''); setSessionSlug(''); setSessionVenue(''); setStartsAt(''); setEndsAt(''); setNotice('Session added.'); void client.invalidateQueries({ queryKey: ['event-sessions', eventId] }) }, onError: error => setNotice(error.message) })
  const saveStaff = useMutation({ mutationFn: () => api(`/api/v1/admin/events/${eventId}/staff`, { method: 'PUT', body: JSON.stringify({ user_ids: assignedIds }) }), onSuccess: () => { setNotice('Event staff saved.'); void client.invalidateQueries({ queryKey: ['event-staff', eventId] }) }, onError: error => setNotice(error.message) })
  const saveProfile = useMutation({ mutationFn: () => api('/api/v1/admin/event-profiles', { method: 'POST', body: JSON.stringify({ name: profileName, location: event?.location || null, venue: event?.venue || null, sessions_template: (sessions.data || []).map(item => ({ name: item.name, venue: item.venue || event?.venue || null, starts_at: item.starts_at || null, ends_at: item.ends_at || null })) }) }), onSuccess: () => { setProfileName(''); setNotice('Reusable event profile saved.'); void client.invalidateQueries({ queryKey: ['event-profiles'] }) }, onError: error => setNotice(error.message) })
  const updateEventMeeting = useMutation({ mutationFn: ({ id, kind, changes }: { id: string; kind: EventMeeting['kind']; changes: object }) => api(`/api/v1/admin/${kind === 'research_meeting' ? 'event-encounters' : 'meetings'}/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }), onSuccess: () => { setNotice('Meeting updated.'); void client.invalidateQueries({ queryKey: ['event-meetings', eventId] }); void client.invalidateQueries({ queryKey: ['event-dashboard', eventId] }); void client.invalidateQueries({ queryKey: ['event-priority-panels', eventId] }) }, onError: error => setNotice(error.message) })
  if (eventQuery.isLoading) return <div className="admin-loading">Loading event…</div>
  if (!event) return <><SectionTitle kicker="EVENT WORKSPACE" title="Event not found"/><Link to="/admin/events" className="admin-action">Back to events</Link></>
  const research = metrics.data?.research || {}
  const activity = metrics.data?.activity || {}
  const cards: [string, number | string, string][] = [
    ['Unique registrants', research.unique_registrants ?? 0, 'Imported research records'],
    ['Shortlist progress', `${research.strong_shortlist ?? 0} / ${research.shortlist_rows ?? 0}`, 'Strong / tagged rows'],
    ['CSE research progress', research.cse_research_rows ?? 0, 'Rows with research status'],
    ['Submissions', activity.submissions ?? 0, `${activity.unique_submitted_contacts ?? 0} unique contacts`],
    ['Quick manual captures', activity.staff_manual_captures ?? 0, 'Staff-entered visitor details'],
    ['People met', activity.unique_people_met ?? 0, 'Distinct research attendees with a recorded meeting or demo'],
    ['Staff-confirmed encounters', activity.staff_confirmed_encounters ?? 0, 'Linked card captures plus research attendee actions'],
    ['Card captures', activity.staff_card_captures ?? 0, 'Staff-uploaded cards; synthetic tests excluded'],
    ['Confirmed meetings', activity.confirmed_meetings ?? 0, 'Meetings recorded'],
    ['Unmatched visitors', activity.unmatched_visitors ?? 0, 'Captured submissions or card records awaiting a research match'],
    ['Outstanding follow-ups', activity.outstanding_follow_ups ?? 0, 'Open meeting next steps'],
  ]
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const followUpsDue = (priorityPanels.data?.follow_ups.items || []).filter(item => {
    const due = new Date(item.due_at)
    due.setHours(0, 0, 0, 0)
    return due <= today
  })
  const activeEventTab = ({ '#meetings': 'meetings', '#follow-ups': 'follow-ups', '#sessions': 'sessions' } as Record<string, string>)[location.hash] || 'overview'
  return <>
    <SectionTitle kicker="EVENT WORKSPACE" title={event.name}><Link to={`/admin/research?eventId=${event.id}`} className="admin-action"><FileSpreadsheet size={15}/> Research</Link></SectionTitle>
    <EventTabNavigation eventId={event.id} active={activeEventTab}/>
    <p className="workspace-event-meta">{dateLabel(event.start_date)}{event.end_date && event.end_date !== event.start_date ? ` – ${dateLabel(event.end_date)}` : ''} · {[event.venue, event.location].filter(Boolean).join(' · ') || 'Venue not set'}</p>
    <div className="workspace-shortcuts"><Link to={`/admin/card-capture?eventId=${event.id}`} className="admin-action">Scan &amp; Save Business Card</Link><Link to={`/admin/research?eventId=${event.id}`} className="admin-action">Import research workbook</Link><EventQR event={event}/></div>
    {metrics.isError && <div className="admin-error">{(metrics.error as Error).message}</div>}
    {priorityPanels.isError && <div className="admin-error">Priority panels could not be loaded: {(priorityPanels.error as Error).message}</div>}
    <div className="workspace-metric-grid">{cards.map(([label, value, hint]) => <article key={label} className="workspace-metric"><span>{label}</span><strong>{value}</strong><small>{hint}</small></article>)}</div>
    <div className="event-priority-grid">
      <section className="workspace-form-card event-priority-panel"><header><div><span className="admin-kicker">SOURCE PRIORITY A / B</span><h2>Must Meet Next</h2><small className="event-priority-breakdown">A {priorityPanels.data?.must_meet_next.priority_counts.A ?? '—'} · B {priorityPanels.data?.must_meet_next.priority_counts.B ?? '—'}</small></div><strong className="event-priority-count">{priorityPanels.data?.must_meet_next.total ?? '—'}</strong></header><p>Only explicit A/B values in the imported Must-Meet field are ranked. Completed staff encounters are removed.</p>
        {priorityPanels.isLoading ? <p className="admin-muted">Loading source priorities…</p> : priorityPanels.data?.must_meet_next.items.length ? <div className="event-priority-list">{priorityPanels.data.must_meet_next.items.map(item => <article key={item.registrant_id}><div className="event-priority-person"><span className={`priority-source-badge priority-${item.priority?.toLowerCase()}`}>Priority {item.priority}</span><strong>{item.full_name || 'Name not provided'}</strong><small>{[item.company, item.job_title].filter(Boolean).join(' · ') || 'Company and designation not provided'}</small></div><small>Latent Sig Fit: {item.fit || 'not provided'} · {item.relationship || 'Relationship not provided'}</small>{item.pitch && <p className="event-priority-pitch">{item.pitch}</p>}<Link className="workspace-link-button" to={`/admin/research?eventId=${event.id}&sheet=${encodeURIComponent(item.sheet_name)}`}>Open {item.sheet_name}</Link></article>)}</div> : <p className="admin-muted">No A/B source-priority targets remain, or no priority workbook is imported.</p>}
        <Link className="event-priority-footer" to={`/admin/research?eventId=${event.id}&sheet=${encodeURIComponent('Strong shortlist')}`}>Open the shortlist worksheet</Link>
      </section>
      <section className="workspace-form-card event-priority-panel"><header><div><span className="admin-kicker">SOURCE FIT &amp; RELATIONSHIP</span><h2>Research Opportunities</h2></div><strong className="event-priority-count">{priorityPanels.data?.research_opportunities.total ?? '—'}</strong></header><p>Strong-fit clients and design partners from workbook fields, excluding A/B must-meet targets.</p>
        {priorityPanels.isLoading ? <p className="admin-muted">Loading research opportunities…</p> : priorityPanels.data?.research_opportunities.items.length ? <div className="event-priority-list">{priorityPanels.data.research_opportunities.items.map(item => <article key={item.registrant_id}><div className="event-priority-person"><strong>{item.full_name || 'Name not provided'}</strong><small>{[item.company, item.job_title].filter(Boolean).join(' · ') || 'Company and designation not provided'}</small></div><small>{item.relationship} · Latent Sig Fit: {item.fit}</small>{item.pitch && <p className="event-priority-pitch">{item.pitch}</p>}<Link className="workspace-link-button" to={`/admin/research?eventId=${event.id}&sheet=${encodeURIComponent(item.sheet_name)}`}>Review source row</Link></article>)}</div> : <p className="admin-muted">No unvisited strong-fit clients or design partners found in source fields.</p>}
      </section>
      <section id="follow-ups" className="workspace-form-card event-priority-panel"><header><div><span className="admin-kicker">OPEN NEXT STEPS</span><h2>Follow-up Today</h2></div><strong className="event-priority-count">{followUpsDue.length}</strong></header><p>Open follow-ups due today or overdue, using your device’s local date.</p>
        {priorityPanels.isLoading ? <p className="admin-muted">Loading follow-ups…</p> : followUpsDue.length ? <div className="event-priority-list">{followUpsDue.slice(0, 8).map(item => <article key={`${item.kind}-${item.id}`}><div className="event-priority-person"><strong>{item.full_name || 'Name not provided'}</strong><small>{item.company || 'Company not provided'} · {new Date(item.due_at).toLocaleDateString()} · {item.status.replaceAll('_', ' ')}</small></div><small>Owner: {item.owner || 'Not assigned'}</small>{item.next_steps && <p className="event-priority-pitch">{item.next_steps}</p>}{item.lead_id && <Link className="workspace-link-button" to={`/admin/leads/${item.lead_id}`}>Open lead</Link>}{!item.lead_id && item.registrant_id && <Link className="workspace-link-button" to={`/admin/research?eventId=${event.id}`}>Open research</Link>}</article>)}</div> : <p className="admin-muted">No open follow-ups are due today or overdue.</p>}
      </section>
      <section className="workspace-form-card event-priority-panel"><header><div><span className="admin-kicker">IMPORT &amp; CAPTURE REVIEW</span><h2>Needs Review</h2></div><strong className="event-priority-count">{(priorityPanels.data?.needs_review.reconciliation_rows ?? 0) + (priorityPanels.data?.needs_review.pending_card_captures ?? 0)}</strong></header><p>{priorityPanels.data?.needs_review.reconciliation_rows ?? 0} research rows need reconciliation · {priorityPanels.data?.needs_review.pending_card_captures ?? 0} card captures need review.</p>
        {priorityPanels.isLoading ? <p className="admin-muted">Loading review queue…</p> : <>{priorityPanels.data?.needs_review.reconciliation_items.map(item => <article className="event-review-row" key={`research-${item.id}`}><span><strong>{item.full_name || 'Research row'}</strong><small>{item.sheet_name} · source row {item.source_row} · {item.errors.join('; ')}</small></span><Link className="workspace-link-button" to={`/admin/research?eventId=${event.id}&sheet=${encodeURIComponent(item.sheet_name)}`}>Review row</Link></article>)}{priorityPanels.data?.needs_review.card_capture_items.map(item => <article className="event-review-row" key={`capture-${item.id}`}><span><strong>{item.name || item.filename}</strong><small>{item.status.replaceAll('_', ' ')} · {new Date(item.captured_at).toLocaleString()}</small></span><Link className="workspace-link-button" to={`/admin/card-capture?eventId=${event.id}`}>Review capture</Link></article>)}{!priorityPanels.data?.needs_review.reconciliation_rows && !priorityPanels.data?.needs_review.pending_card_captures && <p className="admin-muted">No research reconciliation or pending card reviews.</p>}</>}
        <div className="event-priority-actions"><Link className="workspace-link-button" to={`/admin/research?eventId=${event.id}`}>Research imports</Link><Link className="workspace-link-button" to={`/admin/card-capture?eventId=${event.id}`}>Card capture inbox</Link></div>
      </section>
    </div>
    <section id="meetings" className="workspace-form-card event-meeting-section"><header><div><span className="admin-kicker">EVENT MEETINGS</span><h2>Meeting tracker</h2></div><strong className="event-priority-count">{eventMeetings.data?.length ?? '—'}</strong></header>
      <p>Lead and research-attendee meetings in one event list. Research records remain linked to their attendee profiles until a lead is confirmed.</p>
      {eventMeetings.isError && <div className="admin-error">{(eventMeetings.error as Error).message}</div>}
      {eventMeetings.isLoading ? <p className="admin-muted">Loading event meetings…</p> : eventMeetings.data?.length ? <div className="event-meeting-list">{eventMeetings.data.map(item => {
        const canEdit = canManage || item.employee_id === actor.data?.id
        return <article className="workspace-meeting-row" key={`${item.kind}-${item.id}`}><div><strong>{item.full_name || 'Name not provided'} · {item.status}</strong><small>{item.kind === 'research_meeting' ? 'Research attendee' : 'Lead'} · {item.company || 'Company not provided'} · {item.scheduled_at ? new Date(item.scheduled_at).toLocaleString() : 'Time not set'}{item.session_name ? ` · ${item.session_name}` : ''} · {item.topics.join(', ') || 'No topics'}</small>{item.notes && <p>{item.notes}</p>}{item.next_steps && <p>{item.next_steps}</p>}{item.follow_up_due_at && <small>Follow-up {new Date(item.follow_up_due_at).toLocaleDateString()}</small>}{item.lead_id && <Link className="workspace-link-button" to={`/admin/leads/${item.lead_id}`}>Open lead</Link>}{!item.lead_id && item.registrant_id && <Link className="workspace-link-button" to={`/admin/research?eventId=${event.id}`}>Open research profile</Link>}</div><div className="meeting-row-controls"><label>Status<select aria-label={`Status for event meeting ${item.id}`} value={item.status} disabled={!canEdit || updateEventMeeting.isPending} onChange={e => updateEventMeeting.mutate({ id: item.id, kind: item.kind, changes: { status: e.target.value } })}><option value="requested">Requested</option><option value="confirmed">Confirmed</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></label>{canManage && <label>Owner<select aria-label={`Owner for event meeting ${item.id}`} value={item.employee_id || ''} disabled={updateEventMeeting.isPending} onChange={e => updateEventMeeting.mutate({ id: item.id, kind: item.kind, changes: { employee_id: e.target.value || null } })}><option value="">Unassigned</option>{team.data?.filter(person => person.is_active).map(person => <option key={person.id} value={person.id}>{person.full_name}</option>)}</select></label>}</div></article>
      })}</div> : <p className="admin-muted">No meetings have been recorded for this event yet.</p>}
    </section>
    <div className="workspace-management-grid">
      <section id="sessions" className="workspace-form-card"><span className="admin-kicker">SESSIONS &amp; QR LINKS</span><h2>Days &amp; Sessions</h2>
        {sessions.data?.map(session => <article className="workspace-session" key={session.id}><div><strong>{session.name}</strong><small>{session.starts_at ? new Date(session.starts_at).toLocaleString() : 'Time not set'}{session.venue ? ` · ${session.venue}` : ''}</small></div><EventQR event={event} session={session}/></article>)}
        {!sessions.data?.length && <p className="admin-muted">Add sessions to create session-specific QR links.</p>}
        {canManage && <form className="workspace-form-grid" onSubmit={e => { e.preventDefault(); setNotice(''); addSession.mutate() }}>
          <label>Session name<input required value={sessionName} onChange={e => setSessionName(e.target.value)} placeholder="e.g. Expo floor"/></label>
          <label>QR slug<input required value={sessionSlug} onChange={e => setSessionSlug(e.target.value)} pattern="[a-z0-9]+(?:-[a-z0-9]+)*" placeholder="expo-floor"/></label>
          <label>Starts<input type="datetime-local" value={startsAt} onChange={e => setStartsAt(e.target.value)}/></label>
          <label>Ends<input type="datetime-local" value={endsAt} onChange={e => setEndsAt(e.target.value)}/></label>
          <label className="wide-field">Venue<input value={sessionVenue} onChange={e => setSessionVenue(e.target.value)} placeholder={event.venue || event.location || 'Venue'}/></label>
          <button className="admin-primary wide-field" disabled={addSession.isPending}>Add session</button>
        </form>}
      </section>
      {canManage && <section className="workspace-form-card"><span className="admin-kicker">EVENT STAFF</span><h2>Assign staff</h2>
        <div className="workspace-staff-list">{team.data?.filter(person => person.is_active).map(person => <label key={person.id}><input type="checkbox" checked={assignedIds.includes(person.id)} onChange={e => setAssignedIds(ids => e.target.checked ? [...ids, person.id] : ids.filter(id => id !== person.id))}/><span><strong>{person.full_name}</strong><small>{person.email}</small></span></label>)}</div>
        <button className="admin-primary workspace-spaced" onClick={() => saveStaff.mutate()} disabled={saveStaff.isPending}>Save event staff</button>
        <div className="workspace-profile-save"><h3>Reuse this event setup</h3><p>Save the venue and session times as a profile for another event.</p><div><input aria-label="Profile name" value={profileName} onChange={e => setProfileName(e.target.value)} placeholder="Profile name"/><button className="admin-action" disabled={!profileName.trim() || saveProfile.isPending} onClick={() => saveProfile.mutate()}>Save profile</button></div></div>
      </section>}
    </div>
    {notice && <p className="workspace-success" role="status">{notice}</p>}
  </>
}

type ImportQuality = { unique_profile_ids_in_registrants: number; repeated_profile_ids_across_sheets: number; missing_profile_id_rows: number; warning_count: number }
type ImportBatch = { id: string; original_filename: string; file_sha256: string; status: string; sheet_names: string[]; row_count: number; errors: { sheet_name: string; source_row: number; message: string }[]; created_at: string; imported_at?: string; rollback_available: boolean; quality: ImportQuality }
type ImportPreview = { id: string; original_filename: string; file_sha256: string; status: string; row_count: number; sheet_names: string[]; error_count: number; errors: { sheet_name: string; source_row: number; message: string }[]; sheets: { sheet_name: string; columns: string[]; rows: number; errors: number }[]; quality: ImportQuality; rollback_available: boolean }
type Registrant = { id: string; profile_id?: string; full_name?: string; company?: string; job_title?: string; sheet_name: string; source_row: number; shortlist_status?: string; cse_status?: string; match_status: string; reconciliation_required: boolean; reconciliation_errors: string[]; raw_data: Record<string, unknown> }
type ResearchSheet = { sheet_name: string; row_count: number; profile_id_count: number; missing_profile_id_count: number; reconciliation_rows: number; warning_count: number; columns: string[] }
type ResearchSheets = { batch_id: string | null; original_filename: string | null; row_count: number; unique_registrant_profile_ids?: number; sheets: ResearchSheet[] }
type AttendeeMembership = { id: string; profile_id?: string; full_name?: string; company?: string; job_title?: string; sheet_name: string; source_row: number; shortlist_status?: string; cse_status?: string; match_status: string; reconciliation_required: boolean; reconciliation_errors: string[]; raw_data?: Record<string, unknown> }
type ResearchAttendee = { id: string; identity_type: string; profile_id?: string; full_name?: string; company?: string; job_title?: string; website?: string; linkedin?: string; location?: string; sheets: string[]; membership_count: number; match_status: string; reconciliation_required: boolean; reconciliation_errors: string[]; memberships: AttendeeMembership[] }
type ResearchEncounter = { id: string; event_id: string; registrant_id?: string; lead_id?: string; profile_id?: string; full_name?: string; company?: string; session_name?: string; employee_id?: string; employee_name?: string; encounter_type: 'met' | 'demo' | 'meeting'; encountered_at: string; scheduled_at?: string; topics: string[]; notes: string; demo_presented: boolean; status: string; next_steps: string; follow_up_due_at?: string }
type SheetControls = { search: string; page: number; sortBy: string; sortDirection: 'asc' | 'desc'; matchStatus: string; shortlistStatus: string; cseStatus: string; reconciliation: string }
const RESEARCH_PAGE_SIZE = 50
const DEFAULT_SHEET_CONTROLS: SheetControls = { search: '', page: 1, sortBy: '', sortDirection: 'asc', matchStatus: '', shortlistStatus: '', cseStatus: '', reconciliation: '' }

function researchDisplayColumns(sheetName: string, headers: string[]) {
  const normalized = (value: string) => value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
  const rows: Record<string, RegExp[]> = {
    registrants: [/profile id/, /^name$|full name/, /designation|job title/, /^company$|company name/, /website/, /linkedin/, /city|country|location/, /research categor|interest|priority/],
    'strong shortlist': [/^name$|full name/, /^company$|company name/, /must meet|priority|shortlist/, /relationship/, /latentsig fit|fit/, /suggested pitch|pitch|opener/, /meeting|follow up|owner/],
    'design partners': [/^name$|full name/, /^company$|company name/, /partnership/, /technology|product fit|fit/, /research|finding|evidence/, /meeting|status/],
    'clients strong': [/^name$|full name/, /^company$|company name/, /industry|sector/, /business opportunit|opportunit/, /potential solution|solution/, /suggested opener|pitch|follow up/],
    competitors: [/^company$|company name/, /research|finding|evidence/, /competitive overlap|overlap/, /collaboration|partner/, /review|status/],
    'cse research': [/company|^name$|person/, /classification|category/, /evidence|research/, /suggested solution|solution/, /proof point/, /demo|poc/, /caveat|verification|status/],
  }
  const preferred = rows[normalized(sheetName)] || []
  const ranked = preferred.flatMap(pattern => {
    const header = headers.find(candidate => pattern.test(normalized(candidate)))
    return header ? [header] : []
  })
  return [...new Set([...ranked, ...headers])].slice(0, Math.min(8, headers.length))
}

function researchValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function ResearchPage() {
  const [params] = useSearchParams()
  const researchView = params.get('view') || 'research'
  const client = useQueryClient()
  const actor = useQuery({ queryKey: ['admin-me'], queryFn: () => api<Person>('/api/v1/auth/me') })
  const canManage = ['ADMIN', 'MANAGER'].includes(actor.data?.role || '')
  const events = useQuery({ queryKey: ['events'], queryFn: () => api<EventRow[]>('/api/v1/admin/events') })
  const [eventId, setEventId] = useState(params.get('eventId') || '')
  const [defaultEventResolved, setDefaultEventResolved] = useState(Boolean(params.get('eventId')))
  useEffect(() => {
    if (defaultEventResolved || !events.data?.length) return
    const defaultEvent = events.data.find(event => event.slug === 'bts-2026')
      || events.data.find(event => event.is_active)
      || events.data[0]
    setEventId(defaultEvent.id)
    setDefaultEventResolved(true)
  }, [defaultEventResolved, events.data])
  useEffect(() => { setGlobalMode(researchView === 'attendees') }, [researchView, eventId])
  useEffect(() => { if (researchView === 'imports') requestAnimationFrame(() => document.getElementById('research-imports')?.scrollIntoView({ block: 'start' })) }, [researchView, eventId])
  const [file, setFile] = useState<File | null>(null)
  const [activeSheet, setActiveSheet] = useState(params.get('sheet') || '')
  const [sheetControls, setSheetControls] = useState<Record<string, SheetControls>>({})
  const [visibleColumns, setVisibleColumns] = useState<Record<string, string[]>>({})
  const [globalMode, setGlobalMode] = useState(researchView === 'attendees')
  const [globalQuery, setGlobalQuery] = useState('')
  const [globalPage, setGlobalPage] = useState(1)
  const [batchId, setBatchId] = useState('')
  const [previewData, setPreviewData] = useState<ImportPreview | null>(null)
  const [selectedRegistrant, setSelectedRegistrant] = useState<Registrant | null>(null)
  const [selectedProfile, setSelectedProfile] = useState<ResearchAttendee | null>(null)
  const [selectedSessionId, setSelectedSessionId] = useState('')
  const [showMeetingForm, setShowMeetingForm] = useState(false)
  const [meetingScheduledAt, setMeetingScheduledAt] = useState(() => { const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset()); return now.toISOString().slice(0, 16) })
  const [meetingOwnerId, setMeetingOwnerId] = useState('')
  const [meetingStatus, setMeetingStatus] = useState<'requested' | 'confirmed'>('confirmed')
  const [meetingTopics, setMeetingTopics] = useState('')
  const [meetingNotes, setMeetingNotes] = useState('')
  const [meetingDemoPresented, setMeetingDemoPresented] = useState(false)
  const [meetingNextSteps, setMeetingNextSteps] = useState('')
  const [meetingFollowUp, setMeetingFollowUp] = useState('')
  const [encounterNotice, setEncounterNotice] = useState('')
  const [suggestions, setSuggestions] = useState<any[]>([])
  const [notice, setNotice] = useState('')
  const imports = useQuery({ queryKey: ['research-imports', eventId], queryFn: () => api<ImportBatch[]>(`/api/v1/admin/events/${eventId}/research/imports`), enabled: Boolean(eventId) })
  const sheetSummary = useQuery({ queryKey: ['research-sheets', eventId], queryFn: () => api<ResearchSheets>(`/api/v1/admin/events/${eventId}/research/sheets`), enabled: Boolean(eventId) })
  const availableSheets = sheetSummary.data?.sheets || []
  const availableSheetsKey = availableSheets.map(item => item.sheet_name).join('\u0000')
  useEffect(() => {
    if (!availableSheets.length) { setActiveSheet(''); return }
    if (!availableSheets.some(item => item.sheet_name === activeSheet)) setActiveSheet(availableSheets.find(item => item.sheet_name.toLocaleLowerCase() === 'registrants')?.sheet_name || availableSheets[0].sheet_name)
  }, [availableSheetsKey, activeSheet])
  const controls = sheetControls[activeSheet] || DEFAULT_SHEET_CONTROLS
  const registrantParams = new URLSearchParams({ sheet: activeSheet, page: String(controls.page), page_size: String(RESEARCH_PAGE_SIZE) })
  if (controls.search) registrantParams.set('search', controls.search)
  if (controls.matchStatus) registrantParams.set('match_status', controls.matchStatus)
  if (controls.shortlistStatus) registrantParams.set('priority', controls.shortlistStatus)
  if (controls.cseStatus) registrantParams.set('cse_status', controls.cseStatus)
  if (controls.reconciliation) registrantParams.set('reconciliation_required', controls.reconciliation)
  if (controls.sortBy) { registrantParams.set('sort_by', controls.sortBy); registrantParams.set('sort_direction', controls.sortDirection) }
  const registrants = useQuery({ queryKey: ['research-registrants', eventId, activeSheet, controls], queryFn: () => api<{ items: Registrant[]; total: number }>(`/api/v1/admin/events/${eventId}/research/registrants?${registrantParams.toString()}`), enabled: Boolean(eventId && activeSheet && !globalMode) })
  const globalParams = new URLSearchParams({ page: String(globalPage), page_size: String(RESEARCH_PAGE_SIZE) })
  if (globalQuery.trim()) globalParams.set('search', globalQuery.trim())
  const attendees = useQuery({ queryKey: ['research-attendees', eventId, globalQuery, globalPage], queryFn: () => api<{ items: ResearchAttendee[]; total: number }>(`/api/v1/admin/events/${eventId}/research/attendees?${globalParams.toString()}`), enabled: Boolean(eventId && globalMode) })
  const attendeeDetail = useQuery({ queryKey: ['research-attendee-detail', eventId, selectedProfile?.id], queryFn: () => api<ResearchAttendee>(`/api/v1/admin/events/${eventId}/research/attendees/${selectedProfile!.id}`), enabled: Boolean(eventId && selectedProfile) })
  const attendeeEncounters = useQuery({ queryKey: ['research-attendee-encounters', eventId, selectedProfile?.id], queryFn: () => api<ResearchEncounter[]>(`/api/v1/admin/events/${eventId}/research/attendees/${selectedProfile!.id}/encounters`), enabled: Boolean(eventId && selectedProfile) })
  const eventSessions = useQuery({ queryKey: ['event-sessions', eventId], queryFn: () => api<SessionRow[]>(`/api/v1/admin/events/${eventId}/sessions`), enabled: Boolean(eventId && selectedProfile) })
  const team = useQuery({ queryKey: ['team'], queryFn: () => api<Person[]>('/api/v1/admin/team'), enabled: Boolean(canManage && selectedProfile) })
  const preview = useMutation({ mutationFn: () => { const body = new FormData(); body.append('file', file!); return api<ImportPreview>(`/api/v1/admin/events/${eventId}/research/imports`, { method: 'POST', body }) }, onSuccess: result => { setPreviewData(result); setBatchId(result.id); setNotice(`Preview ready: ${result.row_count} rows across ${result.sheet_names.length} worksheets.`); void client.invalidateQueries({ queryKey: ['research-imports', eventId] }) }, onError: error => setNotice(error.message) })
  const confirm = useMutation({ mutationFn: () => api(`/api/v1/admin/research/imports/${batchId}/confirm`, { method: 'POST' }), onSuccess: () => { updateSheetControls({ page: 1 }); setGlobalPage(1); setNotice('Workbook imported. Reimporting this workbook uses the same Profile ID and source-row keys.'); void client.invalidateQueries({ queryKey: ['research-imports', eventId] }); void client.invalidateQueries({ queryKey: ['research-sheets', eventId] }); void client.invalidateQueries({ queryKey: ['research-registrants', eventId] }); void client.invalidateQueries({ queryKey: ['research-attendees', eventId] }); void client.invalidateQueries({ queryKey: ['event-dashboard', eventId] }) }, onError: error => setNotice(error.message) })
  const rollback = useMutation({ mutationFn: (id: string) => api(`/api/v1/admin/research/imports/${id}/rollback`, { method: 'POST' }), onSuccess: () => { updateSheetControls({ page: 1 }); setGlobalPage(1); setNotice('Import rolled back.'); void client.invalidateQueries({ queryKey: ['research-imports', eventId] }); void client.invalidateQueries({ queryKey: ['research-sheets', eventId] }); void client.invalidateQueries({ queryKey: ['research-registrants', eventId] }); void client.invalidateQueries({ queryKey: ['research-attendees', eventId] }); void client.invalidateQueries({ queryKey: ['event-dashboard', eventId] }) }, onError: error => setNotice(error.message) })
  const match = useMutation({ mutationFn: ({ row, leadId }: { row: Registrant; leadId: string }) => api(`/api/v1/admin/events/${eventId}/research/registrants/${row.id}/match`, { method: 'POST', body: JSON.stringify({ lead_id: leadId }) }), onSuccess: () => { setSelectedRegistrant(null); setSuggestions([]); void client.invalidateQueries({ queryKey: ['research-registrants', eventId] }); void client.invalidateQueries({ queryKey: ['event-dashboard', eventId] }) }, onError: error => setNotice(error.message) })
  const createEncounter = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api<ResearchEncounter>(`/api/v1/admin/events/${eventId}/encounters`, { method: 'POST', body: JSON.stringify(payload) }),
    onSuccess: () => { setEncounterNotice('Event action recorded.'); setMeetingNotes(''); setMeetingNextSteps(''); setMeetingTopics(''); setMeetingFollowUp(''); setShowMeetingForm(false); void client.invalidateQueries({ queryKey: ['research-attendee-encounters', eventId, selectedProfile?.id] }); void client.invalidateQueries({ queryKey: ['event-dashboard', eventId] }) },
    onError: error => setEncounterNotice(error.message),
  })
  const updateEncounter = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: object }) => api(`/api/v1/admin/event-encounters/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
    onSuccess: () => { setEncounterNotice('Event action updated.'); void client.invalidateQueries({ queryKey: ['research-attendee-encounters', eventId, selectedProfile?.id] }); void client.invalidateQueries({ queryKey: ['event-dashboard', eventId] }) },
    onError: error => setEncounterNotice(error.message),
  })
  function updateSheetControls(changes: Partial<SheetControls>) { setSheetControls(current => ({ ...current, [activeSheet]: { ...DEFAULT_SHEET_CONTROLS, ...current[activeSheet], ...changes } })) }
  async function downloadSheetExport() {
    try {
      const params = new URLSearchParams({ sheet: activeSheet })
      const response = await fetch(`${apiBase}/api/v1/admin/events/${eventId}/research/export?${params.toString()}`, { credentials: 'include' })
      if (!response.ok) throw new Error('The worksheet export could not be created.')
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = `${activeSheet.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-research.csv`
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'The worksheet export could not be created.')
    }
  }
  async function openMatches(row: Registrant) { setSelectedRegistrant(row); setNotice(''); try { setSuggestions(await api(`/api/v1/admin/events/${eventId}/research/registrants/${row.id}/matches`)) } catch (error) { setNotice(error instanceof Error ? error.message : 'Could not load matches.') } }
  const sheetInfo = availableSheets.find(item => item.sheet_name === activeSheet)
  const headers = sheetInfo?.columns || []
  const defaults = researchDisplayColumns(activeSheet, headers)
  const columns = (visibleColumns[activeSheet] || defaults).filter(column => headers.includes(column))
  function toggleColumn(column: string, enabled: boolean) { setVisibleColumns(current => ({ ...current, [activeSheet]: enabled ? [...(current[activeSheet] || defaults), column].filter((item, index, list) => list.indexOf(item) === index) : (current[activeSheet] || defaults).filter(item => item !== column) })) }
  const canRecordEncounters = ['ADMIN', 'MANAGER', 'SALES'].includes(actor.data?.role || '')
  function recordQuickEncounter(encounterType: 'met' | 'demo') {
    if (!selectedProfile) return
    createEncounter.mutate({
      registrant_id: selectedProfile.id,
      session_id: selectedSessionId || null,
      employee_id: actor.data?.id || undefined,
      encounter_type: encounterType,
      status: 'completed',
      demo_presented: encounterType === 'demo',
    })
  }
  function scheduleResearchMeeting(event: React.FormEvent) {
    event.preventDefault()
    if (!selectedProfile) return
    createEncounter.mutate({
      registrant_id: selectedProfile.id,
      session_id: selectedSessionId || null,
      employee_id: meetingOwnerId || actor.data?.id || undefined,
      encounter_type: 'meeting',
      scheduled_at: meetingScheduledAt ? new Date(meetingScheduledAt).toISOString() : null,
      topics: meetingTopics.split(',').map(value => value.trim()).filter(Boolean),
      notes: meetingNotes,
      demo_presented: meetingDemoPresented,
      status: meetingStatus,
      next_steps: meetingNextSteps,
      follow_up_due_at: meetingFollowUp ? new Date(`${meetingFollowUp}T00:00:00`).toISOString() : null,
    })
  }
  return <>
    <SectionTitle kicker="RESEARCH MANAGEMENT" title="Event research"/>
    {eventId && <EventTabNavigation eventId={eventId} active={globalMode ? 'attendees' : researchView === 'imports' ? 'imports' : 'research'}/>}
    <section className="workspace-form-card research-toolbar"><label>Event<select value={eventId} onChange={e => { setEventId(e.target.value); setActiveSheet(''); setSheetControls({}); setGlobalMode(false); setGlobalQuery(''); setGlobalPage(1) }}><option value="">Choose an event</option>{events.data?.map(event => <option key={event.id} value={event.id}>{event.name}</option>)}</select></label>
      {eventId && canManage && <form className="research-upload" onSubmit={e => { e.preventDefault(); setNotice(''); if (file) preview.mutate() }}><label className="workspace-file"><Upload size={17}/><span>{file?.name || 'Choose an .xlsx or .xlsm workbook'}</span><input type="file" accept=".xlsx,.xlsm" onChange={e => setFile(e.target.files?.[0] || null)}/></label><button className="admin-primary" disabled={!file || preview.isPending}>{preview.isPending ? 'Reading workbook…' : 'Preview workbook'}</button></form>}
      {eventId && !canManage && <p className="admin-muted">Workbook upload and attendee matching are available to event managers.</p>}
      {notice && <p className="workspace-success" role="status">{notice}</p>}
    </section>
    {previewData && <section className="workspace-form-card research-preview"><span className="admin-kicker">IMPORT PREVIEW</span><h2>{previewData.original_filename}</h2><p>{previewData.row_count} data rows · {previewData.sheet_names.length} worksheets · Original file retained privately. Macros are not executed.</p>
      <dl className="research-quality-grid"><div><dt>Source SHA-256</dt><dd className="research-checksum">{previewData.file_sha256}</dd></div><div><dt>Unique Profile IDs in Registrants</dt><dd>{previewData.quality.unique_profile_ids_in_registrants.toLocaleString()}</dd></div><div><dt>Repeated Profile IDs across worksheets</dt><dd>{previewData.quality.repeated_profile_ids_across_sheets.toLocaleString()}</dd></div><div><dt>Rows missing Profile ID</dt><dd>{previewData.quality.missing_profile_id_rows.toLocaleString()}</dd></div><div><dt>Validation warnings</dt><dd>{previewData.quality.warning_count.toLocaleString()}</dd></div><div><dt>Import status</dt><dd>{previewData.status} · rollback unavailable until import</dd></div></dl><p className="admin-muted">Profile IDs are source identifiers and are not independently verified. Review missing IDs and warnings before importing.</p>
      <div className="workspace-preview-sheets">{previewData.sheets.map(item => <article key={item.sheet_name}><strong>{item.sheet_name}</strong><small>{item.rows} rows · {item.columns.length} columns · {item.errors} flagged</small><p>{item.columns.join(' · ')}</p></article>)}</div>
      {previewData.errors.length > 0 && <div className="workspace-warning"><strong>{previewData.errors.length} row(s) need reconciliation</strong>{previewData.errors.slice(0, 20).map((error, index) => <p key={`${error.sheet_name}-${error.source_row}-${index}`}>{error.sheet_name}, row {error.source_row}: {error.message}</p>)}</div>}
      <button className="admin-primary" disabled={confirm.isPending} onClick={() => confirm.mutate()}>{confirm.isPending ? 'Importing…' : 'Confirm import'}</button>
    </section>}
    {eventId && <>
      <section className="workspace-form-card research-workspace"><div className="research-tabs-heading"><div><span className="admin-kicker">WORKSHEET VIEWS</span><h2>Research records</h2></div><span>{sheetSummary.data?.row_count ?? 0} source rows · {sheetSummary.data?.unique_registrant_profile_ids ?? 0} registrant Profile IDs</span></div>
        {sheetSummary.isError && <div className="admin-error" role="alert">{(sheetSummary.error as Error).message}</div>}
        {availableSheets.length > 0 && <div className="research-tabs" role="tablist" aria-label="Research worksheets">{availableSheets.map((item, index) => { const selected = activeSheet === item.sheet_name; return <button type="button" role="tab" tabIndex={selected ? 0 : -1} aria-selected={selected} className={selected ? 'research-tab active' : 'research-tab'} key={item.sheet_name} onClick={() => { setActiveSheet(item.sheet_name); setGlobalMode(false) }} onKeyDown={event => { if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return; event.preventDefault(); const next = (index + (event.key === 'ArrowRight' ? 1 : availableSheets.length - 1)) % availableSheets.length; setActiveSheet(availableSheets[next].sheet_name); setGlobalMode(false); event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus() }}><span>{item.sheet_name.toLocaleLowerCase() === 'registrants' ? 'All registrants' : item.sheet_name}</span><small>{item.row_count.toLocaleString()}</small></button>})}</div>}
        <div className="research-mode-row"><button type="button" className={globalMode ? 'workspace-link-button selected' : 'workspace-link-button'} onClick={() => { setGlobalMode(value => !value); setGlobalPage(1) }}><Search size={14}/>{globalMode ? 'Global search active' : 'Search across all worksheets'}</button>{!globalMode && sheetInfo && <span>{sheetInfo.missing_profile_id_count ? `${sheetInfo.missing_profile_id_count} rows without Profile ID` : 'All rows retain their original worksheet source'}</span>}</div>
        {globalMode ? <>
          <div className="research-controls-row"><label className="research-search"><Search size={16}/><input value={globalQuery} onChange={e => { setGlobalQuery(e.target.value); setGlobalPage(1) }} placeholder="Search Profile ID, name, company, title, website, LinkedIn, or research text"/></label></div>
          <div className="research-results-meta" aria-live="polite"><strong>{attendees.data?.total ?? 0} people across all worksheets</strong><span>Results group only by Profile ID or source identity; matching names alone stay separate.</span></div>
          <div className="research-attendee-list">{attendees.data?.items.map(person => <article className="research-attendee-card" key={person.id}><div><button type="button" className="research-person-link" onClick={() => setSelectedProfile(person)}>{person.full_name || 'Name not provided'}</button><p>{[person.company, person.job_title, person.profile_id ? `Profile ${person.profile_id}` : 'Profile ID not supplied'].filter(Boolean).join(' · ')}</p><small>{person.sheets.map(name => name.toLocaleLowerCase() === 'registrants' ? 'All registrants' : name).join(' · ')} · {person.membership_count} worksheet {person.membership_count === 1 ? 'record' : 'records'}</small></div><div className="research-attendee-flags"><span className={`status-pill ${person.match_status}`}>{person.match_status}</span>{person.reconciliation_required && <span className="reconciliation-tag">Needs reconciliation</span>}<button type="button" className="workspace-link-button" onClick={() => setSelectedProfile(person)}>View profile</button></div></article>)}{attendees.isLoading && <p className="admin-muted">Searching all research worksheets…</p>}{!attendees.isLoading && !attendees.data?.items.length && <p className="admin-muted">{globalQuery ? 'No research profiles match this search.' : 'Enter a name, company, Profile ID, or research term to search all worksheets.'}</p>}</div>
          {attendees.data && attendees.data.total > RESEARCH_PAGE_SIZE && <nav className="research-pagination" aria-label="Attendee search pages"><span>Page {globalPage} of {Math.ceil(attendees.data.total / RESEARCH_PAGE_SIZE)}</span><div><button className="workspace-link-button" disabled={globalPage <= 1} onClick={() => setGlobalPage(page => Math.max(1, page - 1))}>Previous</button><button className="workspace-link-button" disabled={globalPage >= Math.ceil(attendees.data.total / RESEARCH_PAGE_SIZE)} onClick={() => setGlobalPage(page => page + 1)}>Next</button></div></nav>}
        </> : activeSheet ? <>
          <div className="research-toolbar-row research-controls-row"><label className="research-search"><Search size={16}/><input value={controls.search} onChange={e => updateSheetControls({ search: e.target.value, page: 1 })} placeholder={`Search ${activeSheet} columns`}/></label><label className="research-control-select">Match status<select value={controls.matchStatus} onChange={e => updateSheetControls({ matchStatus: e.target.value, page: 1 })}><option value="">All matches</option><option value="matched">Matched</option><option value="suggested">Suggested</option><option value="unmatched">Unmatched</option></select></label><label className="research-control-select">Review<select value={controls.reconciliation} onChange={e => updateSheetControls({ reconciliation: e.target.value, page: 1 })}><option value="">All rows</option><option value="true">Needs reconciliation</option><option value="false">No reconciliation flag</option></select></label>{activeSheet.toLocaleLowerCase() === 'strong shortlist' && <label className="research-control-select">Source priority<select value={controls.shortlistStatus} onChange={e => updateSheetControls({ shortlistStatus: e.target.value, page: 1 })}><option value="">All priorities</option><option value="A">A</option><option value="B">B</option></select></label>}{activeSheet.toLocaleLowerCase() === 'cse research' && <label className="research-control-select">Source CSE status<input value={controls.cseStatus} onChange={e => updateSheetControls({ cseStatus: e.target.value, page: 1 })} placeholder="Filter by source value"/></label>}</div>
          <div className="research-table-tools"><div className="research-results-meta" aria-live="polite"><strong>{registrants.data?.total.toLocaleString() ?? sheetInfo?.row_count.toLocaleString() ?? 0} rows in {activeSheet}</strong><span>{controls.search ? `Search: ${controls.search}` : 'Search and filters apply only to this worksheet.'}</span></div><details className="research-column-picker"><summary>Columns ({columns.length}/{headers.length})</summary><div>{headers.map(header => <label key={header}><input type="checkbox" checked={columns.includes(header)} onChange={e => toggleColumn(header, e.target.checked)}/><span>{header}</span></label>)}</div></details><button type="button" className="workspace-link-button" onClick={() => void downloadSheetExport()}>Export worksheet CSV</button></div>
          <div className="research-table-scroll"><table className="research-table"><thead><tr>{columns.map(column => <th key={column}><button type="button" className="research-sort-button" aria-label={`Sort by ${column}`} onClick={() => updateSheetControls({ sortBy: column, sortDirection: controls.sortBy === column && controls.sortDirection === 'asc' ? 'desc' : 'asc', page: 1 })}>{column}{controls.sortBy === column ? controls.sortDirection === 'asc' ? ' ↑' : ' ↓' : ''}</button></th>)}<th>Match / review</th><th>Actions</th></tr></thead><tbody>{registrants.data?.items.map(row => <tr key={row.id}>{columns.map(column => <td key={column}>{column.toLocaleLowerCase().includes('name') ? <button type="button" className="research-person-link" onClick={() => setSelectedProfile({ id: row.id, identity_type: row.profile_id ? 'profile' : 'source', profile_id: row.profile_id, full_name: row.full_name, company: row.company, job_title: row.job_title, sheets: [row.sheet_name], membership_count: 1, match_status: row.match_status, reconciliation_required: row.reconciliation_required, reconciliation_errors: row.reconciliation_errors, memberships: [] })}>{researchValue(row.raw_data[column] ?? (column.toLocaleLowerCase().includes('name') ? row.full_name : undefined))}</button> : researchValue(row.raw_data[column])}</td>)}<td><span className={`status-pill ${row.match_status}`}>{row.match_status}</span>{row.reconciliation_required && <small className="reconciliation-tag">Needs reconciliation</small>}</td><td><button type="button" className="workspace-link-button" onClick={() => setSelectedProfile({ id: row.id, identity_type: row.profile_id ? 'profile' : 'source', profile_id: row.profile_id, full_name: row.full_name, company: row.company, job_title: row.job_title, sheets: [row.sheet_name], membership_count: 1, match_status: row.match_status, reconciliation_required: row.reconciliation_required, reconciliation_errors: row.reconciliation_errors, memberships: [] })}>Details</button>{canManage && row.match_status !== 'matched' && <button type="button" className="workspace-link-button" onClick={() => void openMatches(row)}>Match</button>}</td></tr>)}</tbody></table>{registrants.isLoading || sheetSummary.isLoading ? <p className="admin-muted">Loading research records…</p> : !registrants.data?.items.length && <p className="admin-muted">{controls.search || controls.matchStatus || controls.shortlistStatus || controls.cseStatus || controls.reconciliation ? 'No rows match these worksheet filters.' : imports.data?.length ? 'No rows are available in this worksheet.' : 'No research workbook has been imported for this event yet.'}</p>}</div>
          {registrants.data && registrants.data.total > RESEARCH_PAGE_SIZE && <nav className="research-pagination" aria-label={`${activeSheet} pages`}><span>Page {controls.page} of {Math.ceil(registrants.data.total / RESEARCH_PAGE_SIZE)}</span><div><button className="workspace-link-button" disabled={controls.page <= 1} onClick={() => updateSheetControls({ page: Math.max(1, controls.page - 1) })}>Previous</button><button className="workspace-link-button" disabled={controls.page >= Math.ceil(registrants.data.total / RESEARCH_PAGE_SIZE)} onClick={() => updateSheetControls({ page: controls.page + 1 })}>Next</button></div></nav>}
        </> : !sheetSummary.isLoading && !sheetSummary.isError && <p className="admin-muted">No research workbook has been imported for this event yet.</p>}
      </section>
      <section id="research-imports" className="workspace-form-card"><span className="admin-kicker">IMPORT HISTORY</span><h2>Source workbooks</h2>{imports.data?.map(item => <article className="workspace-import-row" key={item.id}><div><strong>{item.original_filename}</strong><small>{item.status} · {item.row_count.toLocaleString()} rows · {item.sheet_names.length} worksheets · {item.rollback_available ? 'rollback available' : 'rollback unavailable'} · {new Date(item.created_at).toLocaleString()}</small><small>Profile IDs {item.quality.unique_profile_ids_in_registrants.toLocaleString()} · cross-sheet repeats {item.quality.repeated_profile_ids_across_sheets.toLocaleString()} · missing IDs {item.quality.missing_profile_id_rows.toLocaleString()} · warnings {item.quality.warning_count.toLocaleString()}</small><small className="research-checksum">SHA-256 {item.file_sha256}</small></div><div><button className="workspace-link-button" onClick={async () => { try { const response = await fetch(`${apiBase}/api/v1/admin/research/imports/${item.id}/source`, { credentials: 'include' }); if (!response.ok) throw new Error('Original workbook could not be downloaded.'); const link = document.createElement('a'); link.href = URL.createObjectURL(await response.blob()); link.download = item.original_filename; link.click(); URL.revokeObjectURL(link.href) } catch (reason) { setNotice(reason instanceof Error ? reason.message : 'Download failed.') } }}>Download original</button>{canManage && item.status === 'imported' && <button className="workspace-link-button danger-link" disabled={rollback.isPending} onClick={() => rollback.mutate(item.id)}>Rollback import</button>}</div></article>)}</section>
    </>}
    {selectedProfile && <div className="workspace-modal-backdrop" role="presentation" onMouseDown={e => { if (e.currentTarget === e.target) setSelectedProfile(null) }}><section className="workspace-modal research-profile-modal" role="dialog" aria-modal="true" aria-label="Research attendee profile"><button className="workspace-modal-close" onClick={() => setSelectedProfile(null)}>Close</button><span className="admin-kicker">ATTENDEE RESEARCH PROFILE</span>{attendeeDetail.isLoading ? <p className="admin-muted">Loading all worksheet records…</p> : attendeeDetail.isError ? <div className="admin-error">{(attendeeDetail.error as Error).message}</div> : <><h2>{attendeeDetail.data?.full_name || selectedProfile.full_name || 'Name not provided'}</h2><p>{[attendeeDetail.data?.company || selectedProfile.company, attendeeDetail.data?.job_title || selectedProfile.job_title, (attendeeDetail.data?.profile_id || selectedProfile.profile_id) ? `Profile ${(attendeeDetail.data?.profile_id || selectedProfile.profile_id)}` : 'No Profile ID'].filter(Boolean).join(' · ')}</p><p>{[attendeeDetail.data?.website, attendeeDetail.data?.linkedin, attendeeDetail.data?.location].filter(Boolean).join(' · ') || 'No website, LinkedIn, or location source values'}</p><p className="admin-muted">Identity grouping uses a stable Profile ID, or source-row identity when the ID is missing. Missing details remain blank.</p><h3>Worksheet memberships</h3>{attendeeDetail.data?.memberships.map(membership => <article className="research-membership" key={membership.id}><header><strong>{membership.sheet_name}</strong><span>Source row {membership.source_row}{membership.profile_id ? ` · Profile ${membership.profile_id}` : ' · Missing Profile ID'}</span></header>{membership.reconciliation_required && <p className="reconciliation-tag">Needs reconciliation: {membership.reconciliation_errors.join('; ')}</p>}<details><summary>View all {Object.keys(membership.raw_data || {}).length} source columns</summary><dl>{Object.entries(membership.raw_data || {}).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{researchValue(value)}</dd></div>)}</dl></details></article>)}<h3>Event interactions</h3>{canRecordEncounters && <section className="research-encounter-actions"><p>Record an interaction with this imported attendee. This keeps the encounter linked to research without creating a lead or marking visitor consent.</p><label>Session<select value={selectedSessionId} onChange={e => setSelectedSessionId(e.target.value)}><option value="">No session</option>{eventSessions.data?.map(session => <option key={session.id} value={session.id}>{session.name}</option>)}</select></label><div className="research-quick-actions"><button type="button" className="admin-action" disabled={createEncounter.isPending} onClick={() => recordQuickEncounter('met')}>Mark Met</button><button type="button" className="admin-action" disabled={createEncounter.isPending} onClick={() => recordQuickEncounter('demo')}>Record Demo</button><button type="button" className="admin-action" onClick={() => setShowMeetingForm(value => !value)}>{showMeetingForm ? 'Close meeting form' : 'Schedule Meeting'}</button></div>{showMeetingForm && <form className="meeting-capture-form research-meeting-form" onSubmit={scheduleResearchMeeting}><label>Meeting date and time<input type="datetime-local" value={meetingScheduledAt} onChange={e => setMeetingScheduledAt(e.target.value)}/></label><label>Meeting status<select value={meetingStatus} onChange={e => setMeetingStatus(e.target.value as typeof meetingStatus)}><option value="requested">Requested</option><option value="confirmed">Confirmed</option></select></label>{canManage ? <label>Meeting owner<select value={meetingOwnerId || actor.data?.id || ''} onChange={e => setMeetingOwnerId(e.target.value)}>{team.data?.filter(person => person.is_active).map(person => <option key={person.id} value={person.id}>{person.full_name}</option>)}</select></label> : <label>Meeting owner<input value={actor.data?.full_name || 'Current team member'} readOnly/></label>}<label>Topics<input value={meetingTopics} onChange={e => setMeetingTopics(e.target.value)} placeholder="Comma-separated topics"/></label><label className="meeting-check"><input type="checkbox" checked={meetingDemoPresented} onChange={e => setMeetingDemoPresented(e.target.checked)}/> Demo presented</label><label className="meeting-wide">Notes<textarea value={meetingNotes} onChange={e => setMeetingNotes(e.target.value)} maxLength={10000} placeholder="Discussion notes"/></label><label className="meeting-wide">Next steps<textarea value={meetingNextSteps} onChange={e => setMeetingNextSteps(e.target.value)} maxLength={10000} placeholder="Next action and owner"/></label><label>Follow-up due<input type="date" value={meetingFollowUp} onChange={e => setMeetingFollowUp(e.target.value)}/></label><button className="admin-primary" disabled={createEncounter.isPending}>{createEncounter.isPending ? 'Saving…' : meetingStatus === 'confirmed' ? 'Confirm meeting' : 'Save requested meeting'}</button></form>}{encounterNotice && <p className="workspace-success" role="status">{encounterNotice}</p>}</section>}{attendeeEncounters.isLoading ? <p className="admin-muted">Loading event interactions…</p> : attendeeEncounters.data?.length ? attendeeEncounters.data.map(encounter => <article className="research-encounter-row" key={encounter.id}><div><strong>{encounter.encounter_type === 'met' ? 'Met' : encounter.encounter_type === 'demo' ? 'Demo recorded' : `${encounter.status} meeting`}</strong><small>{encounter.encountered_at ? new Date(encounter.encountered_at).toLocaleString() : 'Date not recorded'}{encounter.scheduled_at ? ` · Scheduled ${new Date(encounter.scheduled_at).toLocaleString()}` : ''}{encounter.session_name ? ` · ${encounter.session_name}` : ''} · {encounter.employee_name || 'Owner not set'}</small>{encounter.topics.length > 0 && <small>Topics: {encounter.topics.join(', ')}</small>}{encounter.notes && <p>{encounter.notes}</p>}{encounter.next_steps && <small>Next steps: {encounter.next_steps}</small>}{encounter.follow_up_due_at && <small>Follow-up due {new Date(encounter.follow_up_due_at).toLocaleDateString()}</small>}{encounter.encounter_type === 'meeting' && (canManage || encounter.employee_id === actor.data?.id) && <label className="research-encounter-status">Meeting status<select aria-label={`Status for research meeting ${encounter.id}`} value={encounter.status} disabled={updateEncounter.isPending} onChange={e => updateEncounter.mutate({ id: encounter.id, changes: { status: e.target.value } })}><option value="requested">Requested</option><option value="confirmed">Confirmed</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></label>}</div></article>) : <p className="admin-muted">No staff-confirmed event interactions have been recorded.</p>}</>}</section></div>}
    {selectedRegistrant && <div className="workspace-modal-backdrop" role="presentation" onMouseDown={e => { if (e.currentTarget === e.target) setSelectedRegistrant(null) }}><section className="workspace-modal" role="dialog" aria-modal="true" aria-label="Review possible matches"><button className="workspace-modal-close" onClick={() => setSelectedRegistrant(null)}>Close</button><span className="admin-kicker">MATCH REVIEW</span><h2>{selectedRegistrant.full_name || 'Research registrant'}</h2><p>{selectedRegistrant.company || 'Company not provided'} · Profile {selectedRegistrant.profile_id || 'not supplied'}</p><p className="admin-muted">Imported prospects are not converted into leads. Link only when the visitor and research record are the same person.</p>{suggestions.filter(item => item.kind === 'lead').map(item => <article className="workspace-candidate" key={item.id}><div><strong>{item.full_name || 'Unnamed lead'}</strong><small>{item.company || ''} · {item.email || item.phone || 'No contact identifier'} · {item.confidence} match</small></div><button className="admin-action" onClick={() => match.mutate({ row: selectedRegistrant, leadId: item.id })}>Link lead</button></article>)}{!suggestions.some(item => item.kind === 'lead') && <p className="admin-muted">No existing lead matched. The research record remains separate until a live submission or staff capture is linked.</p>}</section></div>}
  </>
}

type Capture = { id: string; event_id?: string; event_name?: string; session_id?: string; original_filename: string; status: string; error?: string; ocr: Record<string, any>; lead_id?: string; lead_name?: string; captured_by?: string; created_at?: string; synthetic_test: boolean; candidates: any[] }
type CaptureList = { items: Capture[]; total: number; page: number; page_size: number }
const fieldNames = ['full_name', 'company', 'job_title', 'email', 'phone', 'website', 'address'] as const
const fieldLabels: Record<typeof fieldNames[number], string> = { full_name: 'Name', company: 'Company', job_title: 'Designation', email: 'Email', phone: 'Phone', website: 'Website', address: 'Address' }
type CaptureForm = Record<typeof fieldNames[number], string>
const emptyCapture: CaptureForm = { full_name: '', company: '', job_title: '', email: '', phone: '', website: '', address: '' }
type ManualCandidate = { kind: 'lead' | 'registrant'; id: string; full_name?: string; company?: string; email?: string; phone?: string; confidence: string; matched_by: string; profile_id?: string }
type ManualCaptureResult = { lead_id: string; lead_code: string; lead_name?: string; event_name: string; status: string; created_lead: boolean; matched_research: boolean; captured_by: string; captured_at: string }

function CaptureThumbnail({ captureId }: { captureId: string }) {
  const [src, setSrc] = useState('')
  useEffect(() => {
    let active = true
    let objectUrl = ''
    void fetch(`${apiBase}/api/v1/admin/card-captures/${captureId}/thumbnail`, { credentials: 'include' })
      .then(response => response.ok ? response.blob() : Promise.reject(new Error('Preview unavailable')))
      .then(blob => { objectUrl = URL.createObjectURL(blob); if (active) setSrc(objectUrl) })
      .catch(() => { if (active) setSrc('') })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [captureId])
  return src ? <img className="capture-inbox-thumbnail" src={src} alt="Business card preview"/> : <div className="capture-inbox-thumbnail capture-inbox-thumbnail-empty" aria-label="Card preview unavailable">Preview unavailable</div>
}

function captureName(item: Capture) {
  const value = item.ocr?.full_name
  const name = typeof value === 'string' ? value : typeof value?.value === 'string' ? value.value : ''
  return item.lead_name || name || item.original_filename
}

function captureNextAction(item: Capture) {
  if (item.status === 'pending_match') return 'Resolve possible match'
  if (item.status === 'ocr_failed') return 'Enter card details'
  if (item.status === 'template_detected') return 'Verify card identity'
  if (item.status === 'linked') return 'Review linked capture'
  return 'Review capture'
}

export function StaffCardCapturePage() {
  const actor = useQuery({ queryKey: ['admin-me'], queryFn: () => api<Person>('/api/v1/auth/me') })
  const [params] = useSearchParams()
  const client = useQueryClient()
  const events = useQuery({ queryKey: ['events'], queryFn: () => api<EventRow[]>('/api/v1/admin/events') })
  const policy = useQuery({ queryKey: ['card-capture-policy'], queryFn: () => api<any>('/api/v1/admin/card-capture-policy') })
  const [eventId, setEventId] = useState(params.get('eventId') || '')
  const sessions = useQuery({ queryKey: ['event-sessions', eventId], queryFn: () => api<SessionRow[]>(`/api/v1/admin/events/${eventId}/sessions`), enabled: Boolean(eventId) })
  const [sessionId, setSessionId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [externalConsent, setExternalConsent] = useState(false)
  const [syntheticTest, setSyntheticTest] = useState(false)
  const [capture, setCapture] = useState<Capture | null>(null)
  const [fields, setFields] = useState<CaptureForm>(emptyCapture)
  const [manualFields, setManualFields] = useState<CaptureForm>(emptyCapture)
  const [manualNotes, setManualNotes] = useState('')
  const [manualCandidates, setManualCandidates] = useState<ManualCandidate[]>([])
  const [manualLeadId, setManualLeadId] = useState('')
  const [manualRegistrantId, setManualRegistrantId] = useState('')
  const [manualConfirmDistinct, setManualConfirmDistinct] = useState(false)
  const [manualError, setManualError] = useState('')
  const [manualResult, setManualResult] = useState<ManualCaptureResult | null>(null)
  const [detailsVerified, setDetailsVerified] = useState(false)
  const [selectedLeadId, setSelectedLeadId] = useState('')
  const [selectedRegistrantId, setSelectedRegistrantId] = useState('')
  const [createNewConfirmed, setCreateNewConfirmed] = useState(false)
  const [search, setSearch] = useState('')
  const [includeSynthetic, setIncludeSynthetic] = useState(false)
  const [inboxEventId, setInboxEventId] = useState(params.get('eventId') || '')
  const [inboxStatus, setInboxStatus] = useState('')
  const [inboxNewAfter, setInboxNewAfter] = useState('')
  const [inboxPage, setInboxPage] = useState(1)
  const [error, setError] = useState('')
  const [imageUrl, setImageUrl] = useState('')
  const captureList = useQuery({
    queryKey: ['card-captures', search, includeSynthetic, inboxEventId, inboxStatus, inboxNewAfter, inboxPage],
    queryFn: () => {
      const query = new URLSearchParams({ search, include_synthetic: String(includeSynthetic), page: String(inboxPage), page_size: '25' })
      if (inboxEventId) query.set('event_id', inboxEventId)
      if (inboxStatus) query.set('status', inboxStatus)
      if (inboxNewAfter) query.set('created_after', inboxNewAfter)
      return api<CaptureList>(`/api/v1/admin/card-captures?${query}`)
    },
  })
  const captureMutation = useMutation({
    mutationFn: async () => { const body = new FormData(); body.append('file', file!); if (eventId) body.append('event_id', eventId); if (sessionId) body.append('session_id', sessionId); body.append('external_ai_consent', String(externalConsent)); body.append('synthetic_test', String(syntheticTest)); const result = await api<Capture>('/api/v1/admin/card-captures', { method: 'POST', body }); return result },
    onSuccess: result => { setCapture(result); setFields(Object.fromEntries(fieldNames.map(name => [name, result.ocr?.[name] || ''])) as CaptureForm); setDetailsVerified(false); setSelectedLeadId(''); setSelectedRegistrantId(''); setCreateNewConfirmed(false); setError(''); setFile(null); setExternalConsent(false); setSyntheticTest(false); void client.invalidateQueries({ queryKey: ['card-captures'] }); void client.invalidateQueries({ queryKey: ['admin-leads'] }) },
    onError: reason => setError(reason.message),
  })
  const review = useMutation({
    mutationFn: () => api<Capture>(`/api/v1/admin/card-captures/${capture!.id}/resolve`, { method: 'POST', body: JSON.stringify({ fields, lead_id: selectedLeadId || undefined, registrant_id: selectedRegistrantId || undefined, details_verified: detailsVerified, create_new_confirmed: createNewConfirmed }) }),
    onSuccess: result => { setCapture(result); setSelectedLeadId(''); setSelectedRegistrantId(''); setCreateNewConfirmed(false); setError(''); void client.invalidateQueries({ queryKey: ['card-captures'] }); void client.invalidateQueries({ queryKey: ['admin-leads'] }) },
    onError: reason => setError(reason.message),
  })
  const manualCapture = useMutation({
    mutationFn: () => api<ManualCaptureResult>('/api/v1/admin/manual-captures', { method: 'POST', body: JSON.stringify({
      fields: manualFields, event_id: eventId, session_id: sessionId || undefined,
      notes: manualNotes || undefined, lead_id: manualLeadId || undefined,
      registrant_id: manualRegistrantId || undefined, confirm_distinct: manualConfirmDistinct,
    }) }),
    onSuccess: result => {
      setManualResult(result); setManualFields(emptyCapture); setManualNotes(''); setManualCandidates([])
      setManualLeadId(''); setManualRegistrantId(''); setManualConfirmDistinct(false); setManualError('')
      void client.invalidateQueries({ queryKey: ['admin-leads'] }); void client.invalidateQueries({ queryKey: ['event-dashboard'] })
    },
    onError: reason => {
      try {
        const detail = JSON.parse(reason.message) as { message?: string; candidates?: ManualCandidate[] }
        setManualCandidates(detail.candidates || []); setManualError(detail.message || reason.message)
      } catch { setManualCandidates([]); setManualError(reason.message) }
      setManualLeadId(''); setManualRegistrantId(''); setManualConfirmDistinct(false); setManualResult(null)
    },
  })
  useEffect(() => { if (!capture) { setImageUrl(''); return } let active = true; let objectUrl = ''; void fetch(`${apiBase}/api/v1/admin/card-captures/${capture.id}/image`, { credentials: 'include' }).then(response => response.ok ? response.blob() : Promise.reject(new Error('Card image could not be loaded.'))).then(blob => { objectUrl = URL.createObjectURL(blob); if (active) setImageUrl(objectUrl) }).catch(() => setImageUrl('')); return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) } }, [capture?.id])
  const externalNeedsConsent = policy.data?.external_ai_requires_consent
  const externalAllowed = policy.data?.staff_card_processing_rules_approved
  return <>
    <SectionTitle kicker="STAFF QUICK CAPTURE" title="Scan & Save Business Card"><Link to="/admin/leads" className="admin-action">View leads</Link></SectionTitle>
    {eventId && <EventTabNavigation eventId={eventId} active="captures"/>}
    <div className="capture-page-grid"><section className="workspace-form-card"><span className="admin-kicker">UPLOAD OR PHOTOGRAPH</span><h2>Save a visitor’s card</h2><p>OCR fills what it can. Missing values stay blank; the original image is stored privately for review.</p>
      <form className="capture-form" onSubmit={e => { e.preventDefault(); setError(''); captureMutation.mutate() }}>
        <label>Event<select value={eventId} onChange={e => { setEventId(e.target.value); setSessionId('') }}><option value="">No event attribution</option>{events.data?.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><small>Choose the event the visitor is attending. Unselected captures stay unattributed.</small></label>
        {eventId && <label>Session<select value={sessionId} onChange={e => setSessionId(e.target.value)}><option value="">No session</option>{sessions.data?.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
        <label className="workspace-file capture-file"><Upload size={18}/><span>{file?.name || 'Choose card image or open camera'}</span><input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={e => setFile(e.target.files?.[0] || null)}/></label>
        {actor.data?.role === 'ADMIN' && <label className="capture-consent synthetic-capture-toggle"><input type="checkbox" checked={syntheticTest} onChange={e => { setSyntheticTest(e.target.checked); if (e.target.checked) setExternalConsent(false) }}/><span><strong>Mark this capture as a synthetic test</strong><small>Excluded from event analytics and hidden from recent captures unless synthetic tests are included.</small></span></label>}
        {externalNeedsConsent && <div className="capture-policy-note"><ShieldCheck size={17}/><span>{syntheticTest ? externalAllowed ? 'Approved external OCR may process this synthetic sample. No visitor consent is recorded, and the capture remains excluded from analytics.' : 'External AI OCR is disabled by the current staff-card policy, including for synthetic tests. This image will be saved for manual review.' : externalAllowed ? 'External AI OCR is enabled only when the visitor has agreed to this processing.' : 'External AI OCR is disabled by the current staff-card policy. The image can still be saved for manual review.'}</span></div>}
        {externalNeedsConsent && externalAllowed && !syntheticTest && <label className="capture-consent"><input type="checkbox" checked={externalConsent} onChange={e => setExternalConsent(e.target.checked)}/><span>The visitor explicitly agreed to AI processing of this card image.</span></label>}
        <button className="admin-primary" disabled={!file || captureMutation.isPending}>{captureMutation.isPending ? 'Scanning and saving…' : 'Scan & Save Business Card'}</button>
      </form>{error && <div className="admin-error" role="alert">{error}</div>}
    </section>
    <section className="workspace-form-card capture-review-card"><span className="admin-kicker">CAPTURE REVIEW</span><h2>{capture ? capture.original_filename : 'Your saved capture'}</h2>{capture ? <>
      {imageUrl && <img className="capture-card-image" src={imageUrl} alt="Uploaded business card"/>}
      <div className={`capture-status ${capture.status}`}><strong>{capture.status.replaceAll('_', ' ')}</strong>{capture.event_name && <span>{capture.event_name}</span>}{capture.lead_name && <span>Lead: {capture.lead_name}</span>}</div>
      {capture.synthetic_test && <p className="workspace-success">Synthetic test capture — excluded from event analytics.</p>}
      {capture.error && <p className="workspace-warning-text">{capture.error}</p>}
      {capture.ocr?.is_template && <div className="workspace-warning-text">This image looks like a designed sample or template. Its printed identity values were not saved as a lead. Only save it as a person after you verify the details manually.</div>}
      <div className="capture-fields">{fieldNames.map(name => <label key={name}>{fieldLabels[name]}<input value={fields[name]} onChange={e => setFields(current => ({ ...current, [name]: e.target.value }))} placeholder="Not found on card"/></label>)}</div>
      {capture.ocr?.is_template && <label className="capture-consent"><input type="checkbox" checked={detailsVerified} onChange={e => setDetailsVerified(e.target.checked)}/><span>I verified the entered identity details with the visitor.</span></label>}
      {capture.status === 'pending_match' && capture.candidates?.length > 0 && <div className="workspace-warning"><strong>Possible duplicate matches</strong>{capture.candidates.map(candidate => <div className="workspace-candidate" key={`${candidate.kind}-${candidate.id}`}><span>{candidate.full_name || 'Unnamed'} · {candidate.company || 'Company unknown'} <small>{candidate.kind} · {candidate.confidence}</small></span><button type="button" className="admin-action" onClick={() => { setSelectedLeadId(candidate.kind === 'lead' ? candidate.id : ''); setSelectedRegistrantId(candidate.kind === 'registrant' ? candidate.id : ''); setCreateNewConfirmed(false) }}>Link this record</button></div>)}<label className="capture-consent"><input type="checkbox" checked={createNewConfirmed} onChange={e => { setCreateNewConfirmed(e.target.checked); setSelectedLeadId(''); setSelectedRegistrantId('') }}/><span>I checked these suggestions and this is a different visitor. Create a separate lead.</span></label></div>}
      <button className="admin-primary workspace-spaced" disabled={review.isPending || (capture.ocr?.is_template && !detailsVerified) || (capture.status === 'pending_match' && !selectedLeadId && !selectedRegistrantId && !createNewConfirmed)} onClick={() => review.mutate()}>{review.isPending ? 'Saving review…' : capture.lead_id ? 'Save reviewed fields' : selectedLeadId || selectedRegistrantId ? 'Link selected record' : 'Save as lead'}</button>
      {capture.lead_id && <Link className="workspace-link-button" to={`/admin/leads/${capture.lead_id}`}>Open lead record</Link>}
    </> : <p className="admin-muted">After scanning, the card image, OCR result, event attribution, and review status appear here.</p>}</section></div>
    <section className="workspace-form-card quick-manual-capture"><span className="admin-kicker">QUICK MANUAL CAPTURE</span><h2>Enter the details the visitor provided</h2><p>Save an incomplete visitor record without a card image. Missing details stay blank, and consent is not assumed.</p>
      <form className="quick-manual-form" onSubmit={e => { e.preventDefault(); setManualError(''); manualCapture.mutate() }}>
        <label>Event<select required value={eventId} onChange={e => { setEventId(e.target.value); setSessionId(''); setManualCandidates([]); setManualResult(null) }}><option value="">Choose an active event</option>{events.data?.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {eventId ? <label>Session<select value={sessionId} onChange={e => setSessionId(e.target.value)}><option value="">No session</option>{sessions.data?.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label> : <label>Session<select disabled><option>Choose an event first</option></select></label>}
        {fieldNames.map(name => <label key={name}>{fieldLabels[name]}<input value={manualFields[name]} onChange={e => { setManualFields(current => ({ ...current, [name]: e.target.value })); setManualCandidates([]); setManualResult(null) }} placeholder="Optional" type={name === 'email' ? 'email' : 'text'}/></label>)}
        <label className="quick-manual-notes">Notes<textarea value={manualNotes} onChange={e => setManualNotes(e.target.value)} maxLength={10000} placeholder="What the visitor shared or asked for"/></label>
        {manualCandidates.length > 0 && <div className="quick-manual-match-list"><strong>Review possible matches</strong><p>Choose the person if this is the same visitor. Confirm a different visitor only after checking these suggestions.</p>{manualCandidates.map(candidate => <label className="quick-manual-candidate" key={`${candidate.kind}-${candidate.id}`}><input type="radio" name="manual-candidate" checked={candidate.kind === 'lead' ? manualLeadId === candidate.id : manualRegistrantId === candidate.id} onChange={() => { setManualLeadId(candidate.kind === 'lead' ? candidate.id : ''); setManualRegistrantId(candidate.kind === 'registrant' ? candidate.id : ''); setManualConfirmDistinct(false) }}/><span><strong>{candidate.full_name || 'Name not provided'} · {candidate.company || 'Company not provided'}</strong><small>{candidate.kind === 'registrant' ? `Research attendee${candidate.profile_id ? ` · Profile ${candidate.profile_id}` : ''}` : 'Existing lead'} · {candidate.confidence} match by {candidate.matched_by}{candidate.email ? ` · ${candidate.email}` : ''}{candidate.phone ? ` · ${candidate.phone}` : ''}</small></span></label>)}<label className="capture-consent"><input type="checkbox" checked={manualConfirmDistinct} onChange={e => { setManualConfirmDistinct(e.target.checked); setManualLeadId(''); setManualRegistrantId('') }}/><span>I reviewed the suggestions and this is a different visitor.</span></label></div>}
        {manualError && <div className="admin-error quick-manual-wide" role="alert">{manualError}</div>}
        <button className="admin-primary quick-manual-wide" disabled={!eventId || (!manualFields.full_name.trim() && !manualFields.email.trim() && !manualFields.phone.trim()) || manualCapture.isPending || (manualCandidates.length > 0 && !manualLeadId && !manualRegistrantId && !manualConfirmDistinct)}>{manualCapture.isPending ? 'Saving visitor…' : 'Save quick capture'}</button>
      </form>
      {manualResult && <div className="workspace-success quick-manual-result" role="status"><strong>{manualResult.created_lead ? 'Visitor saved for review' : 'Event capture linked to existing lead'}</strong><span>{manualResult.event_name} · {manualResult.status.replaceAll('_', ' ')} · {new Date(manualResult.captured_at).toLocaleString()}</span>{manualResult.matched_research && <span>Linked to the matching research attendee.</span>}<Link className="workspace-link-button" to={`/admin/leads/${manualResult.lead_id}`}>Open {manualResult.lead_name || manualResult.lead_code}</Link></div>}
    </section>
    <section className="workspace-form-card capture-search-card capture-inbox" aria-label="Business card capture inbox">
      <div className="capture-inbox-heading"><div><span className="admin-kicker">CAPTURE INBOX</span><h2>Recent card captures</h2><p>Review new cards, OCR failures, possible matches, and saved leads.</p></div><label className="research-search"><Search size={16}/><input value={search} onChange={e => { setSearch(e.target.value); setInboxPage(1) }} placeholder="Search name, company, or filename"/></label></div>
      <div className="capture-inbox-filters">
        <label className="research-control-select">Event<select aria-label="Filter captures by event" value={inboxEventId} onChange={e => { setInboxEventId(e.target.value); setInboxPage(1) }}><option value="">All events</option>{events.data?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="research-control-select">Capture status<select aria-label="Filter captures by status" value={inboxNewAfter ? 'new' : inboxStatus} onChange={e => { const value = e.target.value; setInboxStatus(value === 'new' ? '' : value); setInboxNewAfter(value === 'new' ? new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString() : ''); setInboxPage(1) }}><option value="">All captures</option><option value="new">New captures (last 24 hours)</option><option value="pending_review,template_detected">Pending review</option><option value="ocr_failed">OCR failed</option><option value="pending_match">Possible duplicates</option><option value="linked">Linked to lead</option></select></label>
        {actor.data?.role === 'ADMIN' && <label className="synthetic-filter"><input type="checkbox" checked={includeSynthetic} onChange={e => { setIncludeSynthetic(e.target.checked); setInboxPage(1) }}/> Include synthetic tests</label>}
      </div>
      <div className="capture-inbox-summary" aria-live="polite">{captureList.isLoading ? 'Loading captures…' : captureList.data ? `Showing ${captureList.data.total === 0 ? 0 : (captureList.data.page - 1) * captureList.data.page_size + 1}–${Math.min(captureList.data.page * captureList.data.page_size, captureList.data.total)} of ${captureList.data.total.toLocaleString()} captures` : 'Capture list unavailable'}</div>
      {captureList.isError && <div className="admin-error" role="alert">{(captureList.error as Error).message}</div>}
      {captureList.data?.items.map(item => <article className="capture-inbox-row" key={item.id}>
        <CaptureThumbnail captureId={item.id}/>
        <div className="capture-inbox-details"><header><strong>{captureName(item)}</strong><span className={`capture-inbox-status ${item.status}`}>{item.status.replaceAll('_', ' ')}</span></header><small>{item.event_name || 'No event'} · {item.created_at ? new Date(item.created_at).toLocaleString() : 'Capture time unavailable'} · {item.captured_by || 'Staff member unavailable'}</small>{captureName(item) !== item.original_filename && <small>Source file: {item.original_filename}</small>}{item.error && <small className="capture-inbox-error">{item.error}</small>}{item.synthetic_test && <small className="capture-inbox-synthetic">Synthetic test · excluded from analytics</small>}</div>
        <div className="capture-inbox-actions"><button type="button" className="admin-action" onClick={() => { setCapture(item); setFields(Object.fromEntries(fieldNames.map(name => [name, item.ocr?.[name] || ''])) as CaptureForm); setDetailsVerified(false); setSelectedLeadId(''); setSelectedRegistrantId(''); setCreateNewConfirmed(false); requestAnimationFrame(() => document.querySelector('.capture-review-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' })) }}>{captureNextAction(item)}</button>{item.lead_id && <Link className="workspace-link-button" to={`/admin/leads/${item.lead_id}`}>Open lead</Link>}</div>
      </article>)}
      {!captureList.isLoading && !captureList.isError && !captureList.data?.items.length && <p className="admin-muted">No card captures match these filters.</p>}
      {captureList.data && captureList.data.total > captureList.data.page_size && <nav className="research-pagination" aria-label="Card capture pages"><span>Page {inboxPage} of {Math.ceil(captureList.data.total / captureList.data.page_size)}</span><div><button className="workspace-link-button" disabled={inboxPage <= 1} onClick={() => setInboxPage(page => Math.max(1, page - 1))}>Previous</button><button className="workspace-link-button" disabled={inboxPage >= Math.ceil(captureList.data.total / captureList.data.page_size)} onClick={() => setInboxPage(page => page + 1)}>Next</button></div></nav>}
    </section>
  </>
}

export function LeadMeetingPanel({ leadId, interactionId, currentUser, team = [] }: { leadId: string; interactionId?: string; currentUser?: Person; team?: Person[] }) {
  const client = useQueryClient()
  const meetings = useQuery({ queryKey: ['lead-meetings', leadId], queryFn: () => api<any[]>(`/api/v1/admin/leads/${leadId}/meetings`) })
  const [topics, setTopics] = useState('')
  const [notes, setNotes] = useState('')
  const [demo, setDemo] = useState(false)
  const [nextSteps, setNextSteps] = useState('')
  const [followUp, setFollowUp] = useState('')
  const [scheduledAt, setScheduledAt] = useState(() => { const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset()); return now.toISOString().slice(0, 16) })
  const [employeeId, setEmployeeId] = useState('')
  const [status, setStatus] = useState<'requested' | 'confirmed' | 'completed'>('confirmed')
  const [message, setMessage] = useState('')
  const record = useMutation({ mutationFn: () => api(`/api/v1/admin/leads/${leadId}/meetings`, { method: 'POST', body: JSON.stringify({ interaction_id: interactionId || null, scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : null, employee_id: employeeId || currentUser?.id || null, topics: topics.split(',').map(value => value.trim()).filter(Boolean), notes, demo_presented: demo, status, next_steps: nextSteps, follow_up_due_at: followUp ? new Date(`${followUp}T00:00:00`).toISOString() : null }) }), onSuccess: () => { setTopics(''); setNotes(''); setNextSteps(''); setFollowUp(''); setStatus('confirmed'); setMessage('Meeting recorded.'); void client.invalidateQueries({ queryKey: ['lead-meetings', leadId] }); void client.invalidateQueries({ queryKey: ['event-dashboard'] }) }, onError: error => setMessage(error.message) })
  const update = useMutation({ mutationFn: ({ id, changes }: { id: string; changes: object }) => api(`/api/v1/admin/meetings/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }), onSuccess: () => { setMessage('Meeting updated.'); void client.invalidateQueries({ queryKey: ['lead-meetings', leadId] }); void client.invalidateQueries({ queryKey: ['event-dashboard'] }) }, onError: error => setMessage(error.message) })
  const canManage = ['ADMIN', 'MANAGER'].includes(currentUser?.role || '')
  return <section className="detail-card detail-wide"><span className="admin-kicker">MEETINGS &amp; NEXT STEPS</span><h2>Confirm and track a meeting</h2>
    <form className="meeting-capture-form" onSubmit={e => { e.preventDefault(); record.mutate() }}>
      <label>Meeting date and time<input type="datetime-local" value={scheduledAt} onChange={e => setScheduledAt(e.target.value)}/></label>
      <label>Meeting status<select value={status} onChange={e => setStatus(e.target.value as typeof status)}><option value="requested">Requested</option><option value="confirmed">Confirmed</option><option value="completed">Completed</option></select></label>
      {canManage ? <label>Meeting owner<select value={employeeId || currentUser?.id || ''} onChange={e => setEmployeeId(e.target.value)}>{team.filter(person => person.is_active).map(person => <option key={person.id} value={person.id}>{person.full_name}</option>)}</select></label> : <label>Meeting owner<input value={currentUser?.full_name || 'Current team member'} readOnly/></label>}
      <label>Topics<input value={topics} onChange={e => setTopics(e.target.value)} placeholder="Agentic AI, annotation (comma separated)"/></label>
      <label className="meeting-check"><input type="checkbox" checked={demo} onChange={e => setDemo(e.target.checked)}/> Demo presented</label>
      <label className="meeting-wide">Notes<textarea value={notes} onChange={e => setNotes(e.target.value)} maxLength={10000} placeholder="Meeting notes"/></label>
      <label className="meeting-wide">Next steps<textarea value={nextSteps} onChange={e => setNextSteps(e.target.value)} maxLength={10000} placeholder="Who will do what next?"/></label>
      <label>Follow-up due<input type="date" value={followUp} onChange={e => setFollowUp(e.target.value)}/></label>
      <button className="admin-primary" disabled={record.isPending}>{record.isPending ? 'Saving…' : status === 'confirmed' ? 'Confirm meeting' : 'Record meeting'}</button>
    </form>
    {message && <p className="workspace-success" role="status">{message}</p>}{meetings.data?.map(item => { const canEdit = canManage || item.employee_id === currentUser?.id; return <article className="workspace-meeting-row" key={item.id}><div><strong>{item.status} · {item.employee_name || 'Owner not set'}</strong><small>{item.scheduled_at ? new Date(item.scheduled_at).toLocaleString() : 'Time not set'} · {(item.topics || []).join(', ') || 'No topics'}</small>{item.next_steps && <p>{item.next_steps}</p>}</div><div className="meeting-row-controls"><label>Status<select aria-label={`Status for meeting ${item.id}`} value={item.status} disabled={!canEdit || update.isPending} onChange={e => update.mutate({ id: item.id, changes: { status: e.target.value } })}><option value="requested">Requested</option><option value="confirmed">Confirmed</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></label>{canManage && <label>Owner<select aria-label={`Owner for meeting ${item.id}`} value={item.employee_id || ''} disabled={update.isPending} onChange={e => update.mutate({ id: item.id, changes: { employee_id: e.target.value || null } })}><option value="">Unassigned</option>{team.filter(person => person.is_active).map(person => <option key={person.id} value={person.id}>{person.full_name}</option>)}</select></label>}<span>{item.follow_up_due_at ? `Follow-up ${new Date(item.follow_up_due_at).toLocaleDateString()}` : item.demo_presented ? 'Demo presented' : ''}</span></div></article> })}</section>
}
