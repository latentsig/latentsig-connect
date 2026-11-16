import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
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
  const client = useQueryClient()
  const eventQuery = useQuery({ queryKey: ['events'], queryFn: () => api<EventRow[]>('/api/v1/admin/events') })
  const actor = useQuery({ queryKey: ['admin-me'], queryFn: () => api<Person>('/api/v1/auth/me') })
  const events = eventQuery.data || []
  const event = events.find(item => item.id === eventId)
  const metrics = useQuery({ queryKey: ['event-dashboard', eventId], queryFn: () => api<any>(`/api/v1/admin/events/${eventId}/dashboard`), enabled: Boolean(eventId) })
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
  if (eventQuery.isLoading) return <div className="admin-loading">Loading event…</div>
  if (!event) return <><SectionTitle kicker="EVENT WORKSPACE" title="Event not found"/><Link to="/admin/events" className="admin-action">Back to events</Link></>
  const research = metrics.data?.research || {}
  const activity = metrics.data?.activity || {}
  const cards: [string, number | string, string][] = [
    ['Unique registrants', research.unique_registrants ?? 0, 'Imported research records'],
    ['Shortlist progress', `${research.strong_shortlist ?? 0} / ${research.shortlist_rows ?? 0}`, 'Strong / tagged rows'],
    ['CSE research progress', research.cse_research_rows ?? 0, 'Rows with research status'],
    ['Submissions', activity.submissions ?? 0, `${activity.unique_submitted_contacts ?? 0} unique contacts`],
    ['Staff confirmed', activity.staff_confirmed_encounters ?? 0, 'Card encounters'],
    ['Confirmed meetings', activity.confirmed_meetings ?? 0, 'Meetings recorded'],
    ['Unmatched visitors', activity.unmatched_visitors ?? 0, 'Research or card matches to review'],
    ['Outstanding follow-ups', activity.outstanding_follow_ups ?? 0, 'Open meeting next steps'],
  ]
  return <>
    <SectionTitle kicker="EVENT WORKSPACE" title={event.name}><Link to={`/admin/research?eventId=${event.id}`} className="admin-action"><FileSpreadsheet size={15}/> Research</Link></SectionTitle>
    <p className="workspace-event-meta">{dateLabel(event.start_date)}{event.end_date && event.end_date !== event.start_date ? ` – ${dateLabel(event.end_date)}` : ''} · {[event.venue, event.location].filter(Boolean).join(' · ') || 'Venue not set'}</p>
    <div className="workspace-shortcuts"><Link to={`/admin/card-capture?eventId=${event.id}`} className="admin-action">Scan &amp; Save Business Card</Link><Link to={`/admin/research?eventId=${event.id}`} className="admin-action">Import research workbook</Link><EventQR event={event}/></div>
    {metrics.isError && <div className="admin-error">{(metrics.error as Error).message}</div>}
    <div className="workspace-metric-grid">{cards.map(([label, value, hint]) => <article key={label} className="workspace-metric"><span>{label}</span><strong>{value}</strong><small>{hint}</small></article>)}</div>
    <div className="workspace-management-grid">
      <section className="workspace-form-card"><span className="admin-kicker">SESSIONS &amp; QR LINKS</span><h2>Sessions</h2>
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

type ImportBatch = { id: string; original_filename: string; status: string; sheet_names: string[]; row_count: number; errors: { sheet_name: string; source_row: number; message: string }[]; created_at: string }
type ImportPreview = { id: string; original_filename: string; row_count: number; sheet_names: string[]; error_count: number; errors: { sheet_name: string; source_row: number; message: string }[]; sheets: { sheet_name: string; columns: string[]; rows: number; errors: number }[] }
type Registrant = { id: string; profile_id?: string; full_name?: string; company?: string; sheet_name: string; source_row: number; shortlist_status?: string; cse_status?: string; match_status: string; reconciliation_required: boolean; reconciliation_errors: string[]; raw_data: Record<string, unknown> }
const RESEARCH_PAGE_SIZE = 50

export function ResearchPage() {
  const [params] = useSearchParams()
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
  const [file, setFile] = useState<File | null>(null)
  const [query, setQuery] = useState('')
  const [sheet, setSheet] = useState('')
  const [page, setPage] = useState(1)
  const [batchId, setBatchId] = useState('')
  const [previewData, setPreviewData] = useState<ImportPreview | null>(null)
  const [selectedRegistrant, setSelectedRegistrant] = useState<Registrant | null>(null)
  const [suggestions, setSuggestions] = useState<any[]>([])
  const [notice, setNotice] = useState('')
  const imports = useQuery({ queryKey: ['research-imports', eventId], queryFn: () => api<ImportBatch[]>(`/api/v1/admin/events/${eventId}/research/imports`), enabled: Boolean(eventId) })
  const registrants = useQuery({ queryKey: ['research-registrants', eventId, query, sheet, page], queryFn: () => api<{ items: Registrant[]; total: number }>(`/api/v1/admin/events/${eventId}/research/registrants?search=${encodeURIComponent(query)}&sheet=${encodeURIComponent(sheet)}&page=${page}&page_size=${RESEARCH_PAGE_SIZE}`), enabled: Boolean(eventId) })
  const preview = useMutation({ mutationFn: () => { const body = new FormData(); body.append('file', file!); return api<ImportPreview>(`/api/v1/admin/events/${eventId}/research/imports`, { method: 'POST', body }) }, onSuccess: result => { setPreviewData(result); setBatchId(result.id); setNotice(`Preview ready: ${result.row_count} rows across ${result.sheet_names.length} worksheets.`); void client.invalidateQueries({ queryKey: ['research-imports', eventId] }) }, onError: error => setNotice(error.message) })
  const confirm = useMutation({ mutationFn: () => api(`/api/v1/admin/research/imports/${batchId}/confirm`, { method: 'POST' }), onSuccess: () => { setPage(1); setNotice('Workbook imported. Reimporting this workbook uses the same Profile ID and source-row keys.'); void client.invalidateQueries({ queryKey: ['research-imports', eventId] }); void client.invalidateQueries({ queryKey: ['research-registrants', eventId] }); void client.invalidateQueries({ queryKey: ['event-dashboard', eventId] }) }, onError: error => setNotice(error.message) })
  const rollback = useMutation({ mutationFn: (id: string) => api(`/api/v1/admin/research/imports/${id}/rollback`, { method: 'POST' }), onSuccess: () => { setPage(1); setNotice('Import rolled back.'); void client.invalidateQueries({ queryKey: ['research-imports', eventId] }); void client.invalidateQueries({ queryKey: ['research-registrants', eventId] }); void client.invalidateQueries({ queryKey: ['event-dashboard', eventId] }) }, onError: error => setNotice(error.message) })
  const match = useMutation({ mutationFn: ({ row, leadId }: { row: Registrant; leadId: string }) => api(`/api/v1/admin/events/${eventId}/research/registrants/${row.id}/match`, { method: 'POST', body: JSON.stringify({ lead_id: leadId }) }), onSuccess: () => { setSelectedRegistrant(null); setSuggestions([]); void client.invalidateQueries({ queryKey: ['research-registrants', eventId] }); void client.invalidateQueries({ queryKey: ['event-dashboard', eventId] }) }, onError: error => setNotice(error.message) })
  async function openMatches(row: Registrant) { setSelectedRegistrant(row); setNotice(''); try { setSuggestions(await api(`/api/v1/admin/events/${eventId}/research/registrants/${row.id}/matches`)) } catch (error) { setNotice(error instanceof Error ? error.message : 'Could not load matches.') } }
  return <>
    <SectionTitle kicker="RESEARCH MANAGEMENT" title="Registrants & research"/>
    <section className="workspace-form-card research-toolbar"><label>Event<select value={eventId} onChange={e => { setEventId(e.target.value); setPage(1) }}><option value="">Choose an event</option>{events.data?.map(event => <option key={event.id} value={event.id}>{event.name}</option>)}</select></label>
      {eventId && canManage && <form className="research-upload" onSubmit={e => { e.preventDefault(); setNotice(''); if (file) preview.mutate() }}><label className="workspace-file"><Upload size={17}/><span>{file?.name || 'Choose an .xlsx or .xlsm workbook'}</span><input type="file" accept=".xlsx,.xlsm" onChange={e => setFile(e.target.files?.[0] || null)}/></label><button className="admin-primary" disabled={!file || preview.isPending}>{preview.isPending ? 'Reading workbook…' : 'Preview workbook'}</button></form>}
      {eventId && !canManage && <p className="admin-muted">Workbook upload and attendee matching are available to event managers.</p>}
      {notice && <p className="workspace-success" role="status">{notice}</p>}
    </section>
    {previewData && <section className="workspace-form-card research-preview"><span className="admin-kicker">IMPORT PREVIEW</span><h2>{previewData.original_filename}</h2><p>{previewData.row_count} data rows · {previewData.sheet_names.length} worksheets · Original file retained privately. Macros are not executed.</p>
      <div className="workspace-preview-sheets">{previewData.sheets.map(item => <article key={item.sheet_name}><strong>{item.sheet_name}</strong><small>{item.rows} rows · {item.columns.length} columns · {item.errors} flagged</small><p>{item.columns.join(' · ')}</p></article>)}</div>
      {previewData.errors.length > 0 && <div className="workspace-warning"><strong>{previewData.errors.length} row(s) need reconciliation</strong>{previewData.errors.slice(0, 20).map((error, index) => <p key={`${error.sheet_name}-${error.source_row}-${index}`}>{error.sheet_name}, row {error.source_row}: {error.message}</p>)}</div>}
      <button className="admin-primary" disabled={confirm.isPending} onClick={() => confirm.mutate()}>{confirm.isPending ? 'Importing…' : 'Confirm import'}</button>
    </section>}
    {eventId && <>
      <section className="workspace-form-card"><div className="research-toolbar-row"><div><span className="admin-kicker">SEARCH EVERY WORKSHEET</span><h2>Imported registrants</h2></div><label className="research-search"><Search size={16}/><input value={query} onChange={e => { setQuery(e.target.value); setPage(1) }} placeholder="Search names, IDs, companies, or any column"/></label><select className="research-sheet-filter" value={sheet} onChange={e => { setSheet(e.target.value); setPage(1) }}><option value="">All worksheets</option>{imports.data?.flatMap(batch => batch.sheet_names).filter((name, index, all) => all.indexOf(name) === index).map(name => <option key={name}>{name}</option>)}</select></div>
        {registrants.data && registrants.data.total > 0 && <div className="research-results-meta" aria-live="polite"><strong>Showing {(page - 1) * RESEARCH_PAGE_SIZE + 1}–{Math.min(page * RESEARCH_PAGE_SIZE, registrants.data.total)} of {registrants.data.total} registrant rows</strong><span>{sheet || 'All worksheets'}{query ? ` · Search: ${query}` : ''}</span></div>}
        <div className="research-table-scroll"><table className="research-table"><thead><tr><th>Profile ID</th><th>Name / company</th><th>Worksheet</th><th>Shortlist</th><th>CSE</th><th>Match</th><th>Source data</th><th>Review</th></tr></thead><tbody>{registrants.data?.items.map(row => <tr key={row.id}><td>{row.profile_id || '—'}</td><td>{row.full_name || 'Name not provided'}<small>{row.company || ''}</small></td><td>{row.sheet_name}<small>Row {row.source_row}</small></td><td>{row.shortlist_status || '—'}</td><td>{row.cse_status || '—'}</td><td><span className={`status-pill ${row.match_status}`}>{row.match_status}</span>{row.reconciliation_required && <small className="reconciliation-tag">Needs reconciliation</small>}</td><td><details><summary>{Object.keys(row.raw_data).length} columns</summary><dl>{Object.entries(row.raw_data).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value ?? '')}</dd></div>)}</dl></details></td><td>{canManage && row.match_status !== 'matched' && <button className="workspace-link-button" onClick={() => void openMatches(row)}>Match</button>}</td></tr>)}</tbody></table>{(registrants.isLoading || imports.isLoading) ? <p className="admin-muted">Loading research records…</p> : !registrants.data?.items.length && <p className="admin-muted">{query || sheet ? 'No registrants match this search.' : imports.data?.length ? 'No registrants are available in this workbook.' : 'No research workbook has been imported for this event yet.'}</p>}</div>
        {registrants.data && registrants.data.total > RESEARCH_PAGE_SIZE && <nav className="research-pagination" aria-label="Registrant pages"><span>Page {page} of {Math.ceil(registrants.data.total / RESEARCH_PAGE_SIZE)}</span><div><button className="workspace-link-button" aria-label="Previous registrant page" disabled={page <= 1} onClick={() => setPage(current => Math.max(1, current - 1))}>Previous</button><button className="workspace-link-button" aria-label="Next registrant page" disabled={page >= Math.ceil(registrants.data.total / RESEARCH_PAGE_SIZE)} onClick={() => setPage(current => current + 1)}>Next</button></div></nav>}
      </section>
      <section className="workspace-form-card"><span className="admin-kicker">IMPORT HISTORY</span><h2>Source workbooks</h2>{imports.data?.map(item => <article className="workspace-import-row" key={item.id}><div><strong>{item.original_filename}</strong><small>{item.status} · {item.row_count} rows · {new Date(item.created_at).toLocaleString()}</small></div><div><button className="workspace-link-button" onClick={async () => { try { const response = await fetch(`${apiBase}/api/v1/admin/research/imports/${item.id}/source`, { credentials: 'include' }); if (!response.ok) throw new Error('Original workbook could not be downloaded.'); const link = document.createElement('a'); link.href = URL.createObjectURL(await response.blob()); link.download = item.original_filename; link.click(); URL.revokeObjectURL(link.href) } catch (reason) { setNotice(reason instanceof Error ? reason.message : 'Download failed.') } }}>Download original</button>{canManage && item.status === 'imported' && <button className="workspace-link-button danger-link" disabled={rollback.isPending} onClick={() => rollback.mutate(item.id)}>Rollback import</button>}</div></article>)}</section>
    </>}
    {selectedRegistrant && <div className="workspace-modal-backdrop" role="presentation" onMouseDown={e => { if (e.currentTarget === e.target) setSelectedRegistrant(null) }}><section className="workspace-modal" role="dialog" aria-modal="true" aria-label="Review possible matches"><button className="workspace-modal-close" onClick={() => setSelectedRegistrant(null)}>Close</button><span className="admin-kicker">MATCH REVIEW</span><h2>{selectedRegistrant.full_name || 'Research registrant'}</h2><p>{selectedRegistrant.company || 'Company not provided'} · Profile {selectedRegistrant.profile_id || 'not supplied'}</p><p className="admin-muted">Imported prospects are not converted into leads. Link only when the visitor and research record are the same person.</p>{suggestions.filter(item => item.kind === 'lead').map(item => <article className="workspace-candidate" key={item.id}><div><strong>{item.full_name || 'Unnamed lead'}</strong><small>{item.company || ''} · {item.email || item.phone || 'No contact identifier'} · {item.confidence} match</small></div><button className="admin-action" onClick={() => match.mutate({ row: selectedRegistrant, leadId: item.id })}>Link lead</button></article>)}{!suggestions.some(item => item.kind === 'lead') && <p className="admin-muted">No existing lead matched. The research record remains separate until a live submission or staff capture is linked.</p>}</section></div>}
  </>
}

type Capture = { id: string; event_id?: string; event_name?: string; session_id?: string; original_filename: string; status: string; error?: string; ocr: Record<string, any>; lead_id?: string; lead_name?: string; captured_by?: string; synthetic_test: boolean; candidates: any[] }
const fieldNames = ['full_name', 'company', 'job_title', 'email', 'phone', 'website', 'address'] as const
const fieldLabels: Record<typeof fieldNames[number], string> = { full_name: 'Name', company: 'Company', job_title: 'Designation', email: 'Email', phone: 'Phone', website: 'Website', address: 'Address' }
type CaptureForm = Record<typeof fieldNames[number], string>
const emptyCapture: CaptureForm = { full_name: '', company: '', job_title: '', email: '', phone: '', website: '', address: '' }

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
  const [detailsVerified, setDetailsVerified] = useState(false)
  const [selectedLeadId, setSelectedLeadId] = useState('')
  const [selectedRegistrantId, setSelectedRegistrantId] = useState('')
  const [createNewConfirmed, setCreateNewConfirmed] = useState(false)
  const [search, setSearch] = useState('')
  const [includeSynthetic, setIncludeSynthetic] = useState(false)
  const [error, setError] = useState('')
  const [imageUrl, setImageUrl] = useState('')
  const captureList = useQuery({ queryKey: ['card-captures', search, includeSynthetic], queryFn: () => api<{ items: Capture[] }>(`/api/v1/admin/card-captures?search=${encodeURIComponent(search)}&include_synthetic=${includeSynthetic}`) })
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
  useEffect(() => { if (!capture) { setImageUrl(''); return } let active = true; let objectUrl = ''; void fetch(`${apiBase}/api/v1/admin/card-captures/${capture.id}/image`, { credentials: 'include' }).then(response => response.ok ? response.blob() : Promise.reject(new Error('Card image could not be loaded.'))).then(blob => { objectUrl = URL.createObjectURL(blob); if (active) setImageUrl(objectUrl) }).catch(() => setImageUrl('')); return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) } }, [capture?.id])
  const externalNeedsConsent = policy.data?.external_ai_requires_consent
  const externalAllowed = policy.data?.staff_card_processing_rules_approved
  return <>
    <SectionTitle kicker="STAFF QUICK CAPTURE" title="Scan & Save Business Card"><Link to="/admin/leads" className="admin-action">View leads</Link></SectionTitle>
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
    <section className="workspace-form-card capture-search-card"><div className="research-toolbar-row"><div><span className="admin-kicker">ADMIN SEARCH</span><h2>Recent card captures</h2></div><label className="research-search"><Search size={16}/><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search name, company, or filename"/></label><label className="synthetic-filter"><input type="checkbox" checked={includeSynthetic} onChange={e => setIncludeSynthetic(e.target.checked)}/> Include synthetic tests</label></div>
      {captureList.data?.items.map(item => <article className="workspace-import-row" key={item.id}><div><strong>{item.lead_name || item.original_filename}</strong><small>{item.status.replaceAll('_', ' ')} · {item.event_name || 'No event'} · {item.synthetic_test ? 'Synthetic test' : item.captured_by || ''}</small></div><div><button className="workspace-link-button" onClick={() => { setCapture(item); setFields(Object.fromEntries(fieldNames.map(name => [name, item.ocr?.[name] || ''])) as CaptureForm); setDetailsVerified(false); setSelectedLeadId(''); setSelectedRegistrantId(''); setCreateNewConfirmed(false) }}>Review</button>{item.lead_id && <Link className="workspace-link-button" to={`/admin/leads/${item.lead_id}`}>Open lead</Link>}</div></article>)}
      {!captureList.data?.items.length && <p className="admin-muted">No card captures found.</p>}
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
