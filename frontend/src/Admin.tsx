import { useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownToLine, ArrowLeft, BarChart3, Check, ChevronRight, CircleUserRound, LayoutDashboard, LogOut, RefreshCw, Search, Settings, SlidersHorizontal, Users, UserRound } from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import './admin-qr.css'

const configuredApiBase = import.meta.env.VITE_API_BASE_URL || ''
const apiBase = configuredApiBase === '__LATENTSIG_LOCAL_API__'
  ? `${window.location.protocol}//${window.location.hostname}:8000`
  : configuredApiBase
type User = { id: string; email: string; full_name: string; role: string }
type Row = { id: string; lead_code: string; full_name: string; company: string; job_title: string; email: string; email_type: string; phone: string; website?: string; interaction: { id: string; event?: string; interest: string[]; intent: string; status: string; assigned_to?: string; assigned_name?: string; capture_method: string; captured_by?: string; source?: string; business_card?: { has_back: boolean } | null; created_at: string } }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, { ...init, credentials: 'include', headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `Request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const statusNames: Record<string, string> = { new: 'New', contacted: 'Contacted', qualified: 'Qualified', meeting: 'Meeting', proposal: 'Proposal', won: 'Won', follow_up_later: 'Follow up later', not_interested: 'Not interested', lost: 'Lost' }
const stamp = (date: string) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(date))

function CardImageButton({ leadId, interactionId, side = 'front', label = 'View card', className }: { leadId: string; interactionId: string; side?: 'front' | 'back'; label?: string; className?: string }) {
  const [imageUrl, setImageUrl] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const close = () => { if (imageUrl) URL.revokeObjectURL(imageUrl); setImageUrl(''); setError('') }
  const open = async () => {
    setLoading(true); setError('')
    try {
      const response = await fetch(`${apiBase}/api/v1/admin/leads/${leadId}/business-card?interaction_id=${interactionId}&side=${side}`, { credentials: 'include' })
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail || `Could not load card image (${response.status})`)
      }
      setImageUrl(URL.createObjectURL(await response.blob()))
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load card image.') }
    finally { setLoading(false) }
  }
  return <>
    <button type="button" className={className} onClick={() => void open()} disabled={loading} aria-label={`${label} (${side})`}>
      <span>{loading ? 'Loadingâ€¦' : label}</span>
    </button>
    {error && <span className="card-image-error" role="alert">{error}</span>}
    {imageUrl && <div className="card-image-overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) close() }}>
      <section className="card-image-dialog" role="dialog" aria-modal="true" aria-label={`${side} of uploaded business card`}>
        <button type="button" className="card-image-close" onClick={close}>Close</button>
        <img src={imageUrl} alt={`${side} of uploaded business card`} />
      </section>
    </div>}
  </>
}

function AdminLogin() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()
  async function signIn(event: React.FormEvent) {
    event.preventDefault(); setError('')
    try { await request('/api/v1/auth/email-login', { method: 'POST', body: JSON.stringify({ email }) }); navigate('/admin/dashboard') }
    catch (err) { setError(err instanceof Error ? err.message : 'Sign in failed.') }
  }
  return <main className="admin-login"><Link to="/connect" className="admin-brand"><img src="/logo.png" alt="LatentSig"/></Link><section className="login-card"><span className="admin-kicker">TEAM WORKSPACE</span><h1>Welcome back.</h1><p>Sign in to view and manage captured leads.</p><form onSubmit={signIn}><label>Email address<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@latentsig.com" autoComplete="email"/></label>{error && <p className="admin-error" role="alert">{error}</p>}<button className="admin-primary">Sign in</button></form><small>For local use only. Access is limited to the five approved team email addresses.</small></section></main>
}

function AdminGate({ children }: { children: React.ReactNode }) {
  const user = useQuery({ queryKey: ['admin-me'], queryFn: () => request<User>('/api/v1/auth/me'), retry: false })
  if (user.isLoading) return <div className="admin-loading">Loading your workspaceâ€¦</div>
  if (user.isError) return <Navigate to="/admin/login" replace/>
  return <AdminShell user={user.data!}>{children}</AdminShell>
}

function AdminShell({ user, children }: { user: User; children: React.ReactNode }) {
  const queryClient = useQueryClient(); const navigate = useNavigate()
  async function logout() { await request('/api/v1/auth/logout', { method: 'POST' }); await queryClient.clear(); navigate('/admin/login') }
  const links = ([['/admin/dashboard', 'Overview', LayoutDashboard], ['/admin/leads', 'Leads', UserRound], ['/admin/team', 'Team', Users], ['/admin/settings', 'Settings', Settings]] as const).filter(([href]) => (href !== '/admin/team' || ['ADMIN','MANAGER'].includes(user.role)) && (href !== '/admin/settings' || ['ADMIN','MANAGER'].includes(user.role)))
  return <div className="admin-app"><aside className="admin-sidebar"><Link to="/admin/dashboard" className="admin-brand"><img src="/logo.png" alt="LatentSig"/></Link><div className="workspace-label">WORKSPACE</div><nav>{links.map(([href, label, Icon]) => <Link key={href} to={href} className={location.pathname.startsWith(href) ? 'active' : ''}><Icon size={18}/>{label}</Link>)}</nav><button className="logout-button" onClick={logout}><LogOut size={17}/> Sign out</button></aside><div className="admin-main"><header className="admin-topbar"><div><span className="workspace-label">LATENTSIG CONNECT</span><span className="admin-crumb"> / Team workspace</span></div><button className="user-pill" onClick={logout}><span className="user-avatar">{user.full_name.slice(0,1)}</span><span>{user.full_name}<small>{user.role}</small></span><LogOut size={15}/></button></header><main className="admin-content">{children}</main><nav className="admin-mobile-nav">{links.map(([href, label, Icon]) => <Link key={href} to={href}><Icon size={18}/><span>{label}</span></Link>)}</nav></div></div>
}

function PageTitle({ kicker, title, children }: { kicker: string; title: string; children?: React.ReactNode }) { return <div className="admin-page-title"><div><span className="admin-kicker">{kicker}</span><h1>{title}</h1></div>{children}</div> }

function EventQRButton({ slug }: { slug: string }) {
  const [open, setOpen] = useState(false)
  const publicSiteUrl = import.meta.env.VITE_PUBLIC_SITE_URL || window.location.origin
  const captureUrl = new URL('/connect', publicSiteUrl)
  captureUrl.searchParams.set('event', slug)
  captureUrl.searchParams.set('ref', 'booth')
  captureUrl.searchParams.set('utm_source', 'latentsig')
  captureUrl.searchParams.set('utm_medium', 'qr')
  captureUrl.searchParams.set('utm_campaign', slug)
  const downloadSvg = () => {
    const svg = document.querySelector(`[data-event-qr="${slug}"] svg`)
    if (!svg) return
    const objectUrl = URL.createObjectURL(new Blob([svg.outerHTML], { type: 'image/svg+xml' }))
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = `${slug}-capture-qr.svg`
    link.click()
    URL.revokeObjectURL(objectUrl)
  }
  return <div className="event-qr">
    <button type="button" className="event-qr-toggle" aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? 'Hide QR' : 'Show QR'}</button>
    {open && <div className="event-qr-panel">
      <div className="event-qr-image" role="img" aria-label={`QR code for ${slug}`} data-event-qr={slug}><QRCodeSVG value={captureUrl.toString()} size={176} level="M" title={`LatentSig ${slug} capture QR`}/></div>
      <a href={captureUrl.toString()} target="_blank" rel="noreferrer">Open capture link</a>
      <button type="button" className="event-qr-toggle" onClick={downloadSvg}>Download QR image</button>
    </div>}
  </div>
}

function Dashboard() {
  const { data, isLoading, error } = useQuery({ queryKey: ['dashboard'], queryFn: () => request<Record<string, any>>('/api/v1/admin/dashboard') })
  const cards = [['Total leads', data?.total_leads ?? 0], ['New', data?.by_status?.new ?? 0], ['Contacted', data?.by_status?.contacted ?? 0], ['Qualified', data?.by_status?.qualified ?? 0], ['Meetings', data?.by_status?.meeting ?? 0], ['Proposals', data?.by_status?.proposal ?? 0], ['Won', data?.by_status?.won ?? 0]]
  return <><PageTitle kicker="OVERVIEW" title="Dashboard"><Link to="/admin/leads" className="admin-action">View all leads <ChevronRight size={16}/></Link></PageTitle>{error && <div className="admin-error">{(error as Error).message}</div>}{isLoading ? <div className="admin-loading">Loading lead metricsâ€¦</div> : <><div className="metric-grid">{cards.map(([label, value], i) => <article className="metric-card" key={label}><div className="metric-icon"><BarChart3 size={17}/></div><span>{label}</span><strong>{value as number}</strong><small>{i === 0 ? 'All captured contacts' : 'Current pipeline'}</small></article>)}</div><div className="analytics-grid"><MetricList title="Leads by interest" rows={data?.by_interest}/><MetricList title="Leads by team member" rows={data?.by_employee}/><MetricList title="Leads by date" rows={data?.by_date}/><MetricList title="Leads by event" rows={data?.by_event}/><MetricList title="Leads by status" rows={data?.by_status}/><MetricList title="Leads by capture method" rows={data?.by_capture_method}/></div></>}</>
}
function MetricList({ title, rows = {} }: { title: string; rows?: Record<string, number> }) { const entries = Object.entries(rows).sort((a,b) => b[1]-a[1]).slice(0,7); const max = Math.max(1, ...entries.map(([, n]) => n)); return <section className="metric-list"><h2>{title}</h2>{entries.length ? entries.map(([label, count]) => <div className="metric-row" key={label}><div><span>{label.replaceAll('_',' ')}</span><strong>{count}</strong></div><i><b style={{ width: `${count/max*100}%` }}/></i></div>) : <p className="admin-muted">Lead activity will appear here.</p>}</section> }

function Leads() {
  const client = useQueryClient()
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState('created_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [columnsOpen, setColumnsOpen] = useState(false)
  const [visibleColumns, setVisibleColumns] = useState<string[]>(['contact','interest','event','status','captured'])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [bulkAssignee, setBulkAssignee] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const actor = useQuery({ queryKey: ['admin-me'], queryFn: () => request<User>('/api/v1/auth/me') })
  const { data: events = [] } = useQuery({ queryKey: ['events'], queryFn: () => request<any[]>('/api/v1/admin/events') })
  const { data: team = [] } = useQuery({ queryKey: ['team'], queryFn: () => request<User[]>('/api/v1/admin/team'), enabled: ['ADMIN', 'MANAGER'].includes(actor.data?.role || '') })
  const query = new URLSearchParams({ page: String(page), page_size: '25' })
  if (search) query.set('search', search)
  Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value) })
  query.set('sort_by', sortBy); query.set('sort_order', sortOrder)
  const { data, isLoading, isFetching, error, refetch } = useQuery({ queryKey: ['leads', search, filters, page, sortBy, sortOrder], queryFn: () => request<{items: Row[]; total:number}>(`/api/v1/admin/leads?${query}`) })
  const change = (key: string, value: string) => { setFilters(current => ({ ...current, [key]: value })); setPage(1) }
  const clearFilters = () => { setFilters({}); setSearch(''); setPage(1) }
  const activeFilterCount = Object.values(filters).filter(Boolean).length
  const tableColumns = [['lead_code','Lead ID'],['contact','Contact'],['email','Email'],['phone','WhatsApp / phone'],['interest','Interest'],['intent','Intent'],['event','Event / source'],['captured_by','Captured by'],['assigned','Assigned to'],['status','Status'],['captured','Captured at']]
  const allPageSelected = Boolean(data?.items.length && data.items.every(row => selectedIds.includes(row.id)))
  const bulkAssign = useMutation({mutationFn:()=>request<{updated:number}>('/api/v1/admin/leads/bulk-assign',{method:'POST',body:JSON.stringify({lead_ids:selectedIds,assigned_to:bulkAssignee||null})}),onSuccess:()=>{setSelectedIds([]);setBulkAssignee('');void client.invalidateQueries({queryKey:['leads']});void client.invalidateQueries({queryKey:['dashboard']})}})
  const toggleColumn = (column: string) => setVisibleColumns(columns => columns.includes(column) ? columns.filter(item => item !== column) : [...columns, column])
  const sortOptions = [['created_at','Captured date'],['full_name','Name'],['company','Company'],['event','Event'],['status','Status'],['capture_method','Capture method'],['captured_by','Captured by']]
  const filterQuery = new URLSearchParams(Object.entries(filters).filter(([, value]) => Boolean(value)))
  if (search) filterQuery.set('search', search)
  const downloadExcel = async () => {
    setExporting(true); setExportError('')
    try {
      const response = await fetch(`${apiBase}/api/v1/admin/exports/leads.xlsx${filterQuery.size ? `?${filterQuery}` : ''}`, { credentials: 'include' })
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { detail?: string }
        throw new Error(body.detail || `Excel export failed (${response.status})`)
      }
      const disposition = response.headers.get('content-disposition') || ''
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || 'LatentSig_Leads.xlsx'
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a'); link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (reason) { setExportError(reason instanceof Error ? reason.message : 'Excel export failed.') }
    finally { setExporting(false) }
  }
  const select = (key: string, label: string, options: Array<[string, string]>) => <label className="lead-filter"><span>{label}</span><select aria-label={`Filter by ${label}`} value={filters[key] || ''} onChange={e => change(key, e.target.value)}><option value="">All {label.toLowerCase()}</option>{options.map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
  const interests = ['AI Agents','Data & Analytics','Automation','Software Development','QA / Testing','Product Development','Partnership','Other'].map(x=>[x,x] as [string,string])
  const intents = ['I have a project','I need a demo','I am looking for a technology partner','Partnership opportunity','Investment / business discussion','I want to explore LatentSig services','Just connecting','Other'].map(x=>[x,x] as [string,string])
  return <><PageTitle kicker="RELATIONSHIPS" title="Leads"><div className="lead-page-actions"><button type="button" className="admin-action" onClick={() => void refetch()} disabled={isFetching}><RefreshCw size={15} className={isFetching?'spin':''}/> Refresh</button>{['ADMIN','MANAGER','SALES'].includes(actor.data?.role || '')&&<button type="button" className="admin-action" onClick={() => void downloadExcel()} disabled={exporting}><ArrowDownToLine size={16}/> {exporting?'Preparing Excelâ€¦':'Export Excel'}</button>}</div></PageTitle>
    {exportError&&<div className="leads-error" role="alert"><div><strong>Excel export failed</strong><p>{exportError}</p></div></div>}
    <div className="lead-scope-note">{actor.data?.role==='SALES'?'Your assigned leads and the unassigned intake queue are shown here. Unassigned leads are view-only until a manager assigns them.':'Review, filter, assign, and follow up on captured contacts.'}</div>
    <section className="leads-panel">
      <div className="leads-toolbar"><label className="search-box"><Search size={17}/><input value={search} onChange={e=>{setSearch(e.target.value);setPage(1)}} placeholder="Search name, company, email or phone"/></label><button type="button" className={`filter-toggle ${filtersOpen?'is-open':''}`} onClick={()=>setFiltersOpen(value=>!value)}><SlidersHorizontal size={16}/>{filtersOpen?'Hide filters':'Filters'}{activeFilterCount>0&&<span className="filter-count">{activeFilterCount}</span>}</button><button type="button" className={`filter-toggle ${columnsOpen?'is-open':''}`} aria-expanded={columnsOpen} onClick={()=>setColumnsOpen(open=>!open)}>Columns</button></div>
      {columnsOpen&&<fieldset className="column-menu"><legend>Visible columns</legend>{tableColumns.map(([key,label])=><label key={key}><input type="checkbox" checked={visibleColumns.includes(key)} onChange={()=>toggleColumn(key)}/>{label}</label>)}</fieldset>}
      {filtersOpen&&<div className="filter-drawer"><div className="filter-grid">
        <label className="lead-filter"><span>Sort by</span><select aria-label="Sort leads by" value={sortBy} onChange={e=>{setSortBy(e.target.value);setPage(1)}}>{sortOptions.map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label className="lead-filter"><span>Sort order</span><select aria-label="Sort order" value={sortOrder} onChange={e=>{setSortOrder(e.target.value as 'asc'|'desc');setPage(1)}}><option value="desc">Descending</option><option value="asc">Ascending</option></select></label>
        {select('event','Event',events.map((x:any)=>[x.slug,x.name]))}{select('status','Status',Object.entries(statusNames))}{select('interest','Interest',interests)}{select('intent','Intent',intents)}{select('capture_method','Capture method',[['manual','Manual'],['business_card','Business card']])}
        <label className="lead-filter"><span>Captured from</span><input aria-label="Captured by" placeholder="Employee or source" value={filters.captured_by||''} onChange={e=>change('captured_by',e.target.value)}/></label>
        <label className="lead-filter"><span>Date from</span><input aria-label="Date from" type="date" value={filters.date_from||''} onChange={e=>change('date_from',e.target.value)}/></label><label className="lead-filter"><span>Date to</span><input aria-label="Date to" type="date" value={filters.date_to||''} onChange={e=>change('date_to',e.target.value)}/></label>
        {['ADMIN','MANAGER'].includes(actor.data?.role||'')&&select('assigned_to','Assigned to',team.map(person=>[person.id,person.full_name]))}
      </div><div className="filter-drawer-footer"><span>{activeFilterCount?`${activeFilterCount} filter${activeFilterCount===1?'':'s'} applied`:'Choose any combination of filters.'}</span><button type="button" onClick={clearFilters} disabled={!activeFilterCount&&!search}>Clear all</button></div></div>}
      {error?<div className="leads-error"><CircleUserRound size={22}/><div><strong>Couldnâ€™t load leads</strong><p>{(error as Error).message}. Check that the workspace is connected to the same backend where the form was submitted.</p><button type="button" className="empty-clear" onClick={() => void refetch()}>Try again</button></div></div>:isLoading?<div className="admin-loading">Loading leadsâ€¦</div>:data?.items.length?<> {selectedIds.length>0 && ["ADMIN","MANAGER"].includes(actor.data?.role||"") && <div className="bulk-actions"><strong>{selectedIds.length} selected</strong><select aria-label="Assign selected leads" value={bulkAssignee} onChange={e=>setBulkAssignee(e.target.value)}><option value="">Unassign</option>{team.filter(person=>person.role!=="VIEWER").map(person=><option key={person.id} value={person.id}>{person.full_name}</option>)}</select><button type="button" className="admin-primary" disabled={bulkAssign.isPending} onClick={()=>bulkAssign.mutate()}>{bulkAssign.isPending?"Saving?":"Apply assignment"}</button><button type="button" className="empty-clear" onClick={()=>setSelectedIds([])}>Clear selection</button>{bulkAssign.error&&<span role="alert">{bulkAssign.error.message}</span>}</div>}<div className="results-meta"><strong>{data.total} {data.total===1?'lead':'leads'}</strong>{search||activeFilterCount>0?<span>Matching your search and filters</span>:null}</div><div className="lead-table-wrap"><table className="lead-table"><thead><tr>
        {['ADMIN','MANAGER'].includes(actor.data?.role||'')&&<th><input type="checkbox" aria-label="Select all leads on this page" checked={allPageSelected} onChange={event=>setSelectedIds(event.target.checked?[...new Set([...selectedIds,...(data?.items||[]).map(row=>row.id)])]:selectedIds.filter(id=>!data?.items.some(row=>row.id===id)))} /></th>}
        {tableColumns.map(([key,label])=><th key={key} hidden={!visibleColumns.includes(key)}>{label}</th>)}<th/></tr></thead><tbody>{data.items.map(row=><tr key={row.id}>
        {['ADMIN','MANAGER'].includes(actor.data?.role||'')&&<td><input type="checkbox" aria-label={`Select ${row.full_name}`} checked={selectedIds.includes(row.id)} onChange={event=>setSelectedIds(ids=>event.target.checked?[...ids,row.id]:ids.filter(id=>id!==row.id))}/></td>}
        <td hidden={!visibleColumns.includes('lead_code')}>{row.lead_code}</td>
        <td hidden={!visibleColumns.includes('contact')}><Link to={`/admin/leads/${row.id}`} className="table-person"><strong>{row.full_name}</strong><span>{[row.job_title,row.company].filter(Boolean).join(' ? ')}</span></Link></td>
        <td hidden={!visibleColumns.includes('email')}><a href={`mailto:${row.email}`}>{row.email}</a></td>
        <td hidden={!visibleColumns.includes('phone')}><a href={`https://wa.me/${String(row.phone).replace(/\D/g,'')}`} target="_blank" rel="noreferrer">{row.phone}</a></td>
        <td hidden={!visibleColumns.includes('interest')}>{row.interaction.interest.map(x=><span className="mini-tag" key={x}>{x}</span>)}</td>
        <td hidden={!visibleColumns.includes('intent')}>{row.interaction.intent}</td>
        <td hidden={!visibleColumns.includes('event')}><strong>{row.interaction.event||'Event'}</strong><span className="table-sub">{row.interaction.source||'Direct'}</span><span className="capture-method-pill">{row.interaction.capture_method==='business_card'?'Business card':'Manual entry'}</span>{row.interaction.capture_method==='business_card'&&row.interaction.business_card&&<CardImageButton leadId={row.id} interactionId={row.interaction.id} className="lead-card-preview"/>}</td>
        <td hidden={!visibleColumns.includes('captured_by')}>{row.interaction.captured_by||'Unattributed'}</td>
        <td hidden={!visibleColumns.includes('assigned')}>{row.interaction.assigned_name||'Unassigned'}</td>
        <td hidden={!visibleColumns.includes('status')}><span className={`status-pill ${row.interaction.status}`}>{statusNames[row.interaction.status]||row.interaction.status}</span></td>
        <td hidden={!visibleColumns.includes('captured')}>{stamp(row.interaction.created_at)}</td>
        <td><Link className="row-view" to={`/admin/leads/${row.id}`}>View <ChevronRight size={15}/></Link></td></tr>)}</tbody></table></div><div className="lead-mobile-list">{data.items.map(row=><Link className="lead-mobile-card" key={row.id} to={`/admin/leads/${row.id}`}><div><strong>{row.full_name}</strong><span>{[row.company,row.job_title].filter(Boolean).join(' Â· ')}</span></div><div className="mobile-status"><span className={`status-pill ${row.interaction.status}`}>{statusNames[row.interaction.status]}</span>{!row.interaction.assigned_to&&<span className="assignment-pending">Unassigned</span>}</div><div className="lead-card-foot"><span>{row.interaction.interest.join(' Â· ')}</span><span className="capture-method-pill">{row.interaction.capture_method === 'business_card' ? 'Business card' : 'Manual entry'}</span><span>{stamp(row.interaction.created_at)}</span></div>{row.interaction.capture_method === 'business_card' && row.interaction.business_card && <span className="lead-card-mobile-image">Business card uploaded · open lead to view</span>}</Link>)}</div><div className="pagination"><span>{data.total} leads</span><div><button disabled={page<=1} onClick={()=>setPage(page-1)}>Previous</button><span>Page {page}</span><button disabled={page*25>=data.total} onClick={()=>setPage(page+1)}>Next</button></div></div></>:<div className="empty-state"><CircleUserRound size={30}/><h2>{search||activeFilterCount?'No matching leads':'No leads to show yet'}</h2><p>{search||activeFilterCount?'Try clearing your search or filters.':actor.data?.role==='SALES'?'No leads are currently visible to you. Unassigned submissions and leads assigned to you appear here.':'No submissions were found in this workspace. Check that you are viewing the same environment where the form was submitted.'}</p>{(search||activeFilterCount>0)&&<button type="button" className="empty-clear" onClick={clearFilters}>Clear search and filters</button>}</div>}
    </section></>
}

function LeadDetail() {
  const { id = '' } = useParams(); const client = useQueryClient(); const navigate = useNavigate(); const [note,setNote]=useState('')
  const {data,isLoading} = useQuery({queryKey:['lead',id],queryFn:()=>request<any>(`/api/v1/admin/leads/${id}`)})
  const actor = useQuery({queryKey:['admin-me'],queryFn:()=>request<User>('/api/v1/auth/me')})
  const team = useQuery({queryKey:['team'],queryFn:()=>request<any[]>('/api/v1/admin/team'),enabled:['ADMIN','MANAGER'].includes(actor.data?.role||'')})
  const update = useMutation({mutationFn:(value:object)=>request(`/api/v1/admin/leads/${id}`,{method:'PATCH',body:JSON.stringify(value)}),onSuccess:()=>{void client.invalidateQueries({queryKey:['lead',id]});void client.invalidateQueries({queryKey:['leads']});void client.invalidateQueries({queryKey:['dashboard']})}})
  const saveNote = useMutation({mutationFn:()=>request(`/api/v1/admin/leads/${id}/notes`,{method:'POST',body:JSON.stringify({note})}),onSuccess:()=>{setNote('');void client.invalidateQueries({queryKey:['lead',id]})}})
  const removeLead = useMutation({mutationFn:()=>request(`/api/v1/admin/leads/${id}`,{method:'DELETE'}),onSuccess:()=>{void client.invalidateQueries({queryKey:['leads']});navigate('/admin/leads')}})
  if(isLoading)return <div className="admin-loading">Loading contactâ€¦</div>
  if(!data)return <div className="admin-error">Lead not found.</div>
  const latest = data.interactions?.[0] || {}
  const statusOptions = Object.entries(statusNames)
  const salesCanAct = actor.data?.role !== 'SALES' || latest.assigned_to === actor.data?.id
  const wa = `https://wa.me/${String(data.phone).replace(/\D/g, '')}?text=${encodeURIComponent('Hi ' + data.full_name + ', we connected at ' + (latest.event || 'a LatentSig event') + '. I would like to continue our discussion.')}`
  return <>
    <Link to="/admin/leads" className="back-link"><ArrowLeft size={16}/> Back to leads</Link>
    <PageTitle kicker={data.lead_code} title={data.full_name}>
      <span className={`status-pill ${latest.status}`}>{statusNames[latest.status]}</span>
      {actor.data?.role === 'ADMIN' && <button className="admin-action" onClick={() => { if (window.confirm(`Delete ${data.full_name} and all interactions?`)) removeLead.mutate() }} disabled={removeLead.isPending}>Delete lead</button>}
    </PageTitle>
    <div className="detail-grid">
      <section className="detail-card">
        <span className="admin-kicker">CONTACT DETAILS</span><h2>{data.company}</h2><p className="admin-muted">{data.job_title}</p>
        <dl>
          <dt>Email</dt><dd><a href={`mailto:${data.email}`}>{data.email}</a><small>{data.email_type} email</small></dd>
          <dt>WhatsApp / phone</dt><dd><a href={wa} target="_blank" rel="noreferrer">{data.phone}</a></dd>
          <dt>Website</dt><dd>{data.website ? <a href={data.website} target="_blank" rel="noreferrer">{data.website}</a> : '?'}</dd>
        </dl>
        <div className="detail-actions"><a href={wa} target="_blank" rel="noreferrer">WhatsApp</a><a href={`mailto:${data.email}`}>Email</a></div>
      </section>
      <section className="detail-card">
        <span className="admin-kicker">FOLLOW-UP</span><h2>Lead management</h2>
        {actor.data?.role !== 'VIEWER' && salesCanAct && <label className="admin-field">Status<select value={latest.status || 'new'} onChange={e => update.mutate({ status: e.target.value })}>{statusOptions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>}
        {actor.data?.role === 'ADMIN' || actor.data?.role === 'MANAGER' ? <label className="admin-field">Assigned to<select value={latest.assigned_to || ''} onChange={e => update.mutate({ assigned_to: e.target.value || null })}><option value="">Unassigned</option>{team.data?.map((person: any) => <option key={person.id} value={person.id}>{person.full_name}</option>)}</select></label> : <p className="admin-muted">Assigned to: {latest.assigned_name || 'Unassigned'}</p>}
        {actor.data?.role === 'SALES' && !salesCanAct && <p className="assignment-help">This lead is in the unassigned queue. A manager needs to assign it before you can change its status or add notes.</p>}
        <div className="detail-context"><span className="history-card-label">Latest submission</span><strong>{latest.event || 'LatentSig event'}</strong><span>{latest.interest?.join(' Â· ')}</span><span>{latest.intent}</span><span>{latest.capture_method === 'business_card' ? 'Business card' : 'Manual entry'} Â· {stamp(latest.created_at)}</span>{latest.other_interest_details && <p>Other interest: {latest.other_interest_details}</p>}{latest.other_intent_details && <p>Other discussion: {latest.other_intent_details}</p>}{latest.requirement_message && <p>Visitor feedback: {latest.requirement_message}</p>}{!latest.other_interest_details && !latest.other_intent_details && !latest.requirement_message && <p>No additional details</p>}
          {latest.capture_method === 'business_card' && latest.business_card && <div className="history-card-images"><span className="history-card-label">Card uploaded for this submission</span><div className="history-card-thumbnails"><CardImageButton leadId={id!} interactionId={latest.id} side="front" label="View front" className="history-card-view"/>{latest.business_card.has_back && <CardImageButton leadId={id!} interactionId={latest.id} side="back" label="View back" className="history-card-view"/>}</div></div>}
        </div>
      </section>
      <section className="detail-card detail-wide">
        <span className="admin-kicker">TEAM NOTES</span><h2>Keep the conversation moving</h2>
        <form className="note-form" onSubmit={e => { e.preventDefault(); saveNote.mutate() }}><textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Add a private note for the team?" maxLength={5000}/><button disabled={!note.trim() || saveNote.isPending}>Add note</button></form>
        {data.notes?.map((item: any) => <article className="note-item" key={item.id}><p>{item.note}</p><span>{item.author} Â· {stamp(item.created_at)}</span></article>)}
      </section>
      {data.interactions?.length > 1 && <section className="detail-card detail-wide">
        <span className="admin-kicker">PREVIOUS SUBMISSIONS</span><h2>Earlier forms for this contact</h2><p className="history-note">Contacts with the same email or phone are kept together. These are earlier submissions; each card image belongs to the submission marked Business card.</p>
        {data.interactions.slice(1).map((item: any) => <article className="note-item history-item" key={item.id}>
          <strong>{item.event || 'LatentSig event'} Â· {stamp(item.created_at)}</strong>
          <p>{item.interest?.join(' Â· ')} Â· {item.intent}</p>
          {item.other_interest_details && <p>Other interest: {item.other_interest_details}</p>}
          {item.other_intent_details && <p>Other discussion: {item.other_intent_details}</p>}
          {item.requirement_message && <p>Visitor feedback: {item.requirement_message}</p>}
          <span>{item.capture_method === 'business_card' ? 'Business card' : 'Manual'} Â· {item.status} Â· {item.captured_by || 'Unattributed'}</span>
          {item.capture_method === 'business_card' && item.business_card && <div className="history-card-images"><span className="history-card-label">Card uploaded for this business card submission</span><div className="history-card-thumbnails"><CardImageButton leadId={id!} interactionId={item.id} side="front" label="View front" className="history-card-view"/>{item.business_card.has_back && <CardImageButton leadId={id!} interactionId={item.id} side="back" label="View back" className="history-card-view"/>}</div></div>}
        </article>)}
      </section>}
    </div>
  </>
}

function Team() { const client=useQueryClient(); const {data=[],isLoading,error}=useQuery({queryKey:['team'],queryFn:()=>request<any[]>('/api/v1/admin/team')}); const save=useMutation({mutationFn:({id,...body}:any)=>request(`/api/v1/admin/team/${id}`,{method:'PATCH',body:JSON.stringify(body)}),onSuccess:()=>void client.invalidateQueries({queryKey:['team']})}); return <><PageTitle kicker="PEOPLE" title="Team access"/><section className="leads-panel">{error&&<div className="admin-error">{(error as Error).message}</div>}{isLoading?<div className="admin-loading">Loading teamâ€¦</div>:data.map((person:any)=><div className="team-row" key={person.id}><span className="user-avatar"><UserRound size={17}/></span><div className="team-member"><strong>{person.full_name}</strong><span>{person.email}</span></div><select aria-label={`${person.full_name} role`} value={person.role} onChange={e=>save.mutate({id:person.id,full_name:person.full_name,role:e.target.value,is_active:person.is_active})}>{['ADMIN','MANAGER','SALES','VIEWER'].map(role=><option key={role}>{role}</option>)}</select><label className="team-active"><input type="checkbox" checked={person.is_active} onChange={e=>save.mutate({id:person.id,full_name:person.full_name,role:person.role,is_active:e.target.checked})}/> Active</label><Check size={16} className="saved-mark"/></div>)}</section><p className="admin-muted">The local email list controls who can sign in. New team members are added on their first sign-in.</p></> }

function SettingsPage() { const client=useQueryClient();const actor=useQuery({queryKey:['admin-me'],queryFn:()=>request<User>('/api/v1/auth/me')});const {data:settings}=useQuery({queryKey:['settings'],queryFn:()=>request<any>('/api/v1/admin/settings')});const {data:events=[]}=useQuery({queryKey:['events'],queryFn:()=>request<any[]>('/api/v1/admin/events')});const [name,setName]=useState('');const [slug,setSlug]=useState('');const [location,setLocation]=useState('');const [message,setMessage]=useState('');const create=useMutation({mutationFn:()=>request('/api/v1/admin/events',{method:'POST',body:JSON.stringify({name,slug,location,is_active:true})}),onSuccess:()=>{setName('');setSlug('');setLocation('');setMessage('Event created.');void client.invalidateQueries({queryKey:['events']})},onError:e=>setMessage(e.message)});const updateEvent=useMutation({mutationFn:(event:any)=>request(`/api/v1/admin/events/${event.id}`,{method:'PATCH',body:JSON.stringify({...event,is_active:!event.is_active})}),onSuccess:()=>void client.invalidateQueries({queryKey:['events']}),onError:e=>setMessage(e.message)});useEffect(()=>{if(name&&!slug)setSlug(name.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,''))},[name,slug]);return <><PageTitle kicker="CONFIGURATION" title="Settings"/><div className="settings-grid"><section className="detail-card"><span className="admin-kicker">EVENTS</span><h2>Capture links</h2><p className="admin-muted">Each active event gets an attribution slug for QR links.</p>{events.map((event:any)=><div className="event-row" key={event.id}><div><strong>{event.name}</strong><EventQRButton slug={event.slug}/></div>{actor.data?.role==='ADMIN'?<button type="button" className={event.is_active?'active-dot':'inactive-dot'} onClick={()=>updateEvent.mutate(event)}>{event.is_active?'Active ? pause':'Inactive ? activate'}</button>:<span className={event.is_active?'active-dot':'inactive-dot'}>{event.is_active?'Active':'Inactive'}</span>}</div>)}{actor.data?.role==='ADMIN'&&<form className="event-form" onSubmit={e=>{e.preventDefault();create.mutate()}}><h3>Add event</h3><input required value={name} onChange={e=>setName(e.target.value)} placeholder="Event name"/><input required value={slug} onChange={e=>setSlug(e.target.value)} placeholder="event-slug" pattern="[a-z0-9]+(?:-[a-z0-9]+)*"/><input value={location} onChange={e=>setLocation(e.target.value)} placeholder="Location (optional)"/><button className="admin-primary" disabled={create.isPending}>Create event</button>{message&&<small>{message}</small>}</form>}</section><section className="detail-card"><span className="admin-kicker">INTEGRATIONS</span><h2>Connected services</h2><div className="integration-row"><span>Team sign-in</span><b>Local email allowlist</b></div><div className="integration-row"><span>Google Sheets sync</span><b>{settings?.google_sheets_enabled?'Enabled':'Not connected'}</b></div><div className="integration-row"><span>Private card storage</span><b>{settings?.storage_provider||'local'}</b></div><div className="integration-row"><span>WhatsApp follow-up</span><b>{settings?.whatsapp_configured?'Configured':'Not configured'}</b></div><div className="integration-row"><span>Card image retention</span><b>{settings?.business_card_retention_days??90} days</b></div><p className="admin-muted">Set integration credentials in the backend environment. Secret values are never shown here.</p></section></div></> }

export default function Admin() { return <Routes><Route path="login" element={<AdminLogin/>}/><Route path="" element={<Navigate to="/admin/dashboard" replace/>}/><Route path="dashboard" element={<AdminGate><Dashboard/></AdminGate>}/><Route path="leads" element={<AdminGate><Leads/></AdminGate>}/><Route path="leads/:id" element={<AdminGate><LeadDetail/></AdminGate>}/><Route path="team" element={<AdminGate><Team/></AdminGate>}/><Route path="settings" element={<AdminGate><SettingsPage/></AdminGate>}/><Route path="*" element={<Navigate to="/admin/dashboard" replace/>}/></Routes> }
