import { useEffect, useMemo, useState } from 'react'

const tokenKey = 'douyin-admin-token'

function authHeaders() {
  const token = localStorage.getItem(tokenKey) || ''
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(options.headers || {}) },
  })
  if (!response.ok) throw new Error(await response.text())
  return response.status === 204 ? null : response.json()
}

function formatDate(value) {
  if (!value) return '—'
  return value.length === 8 ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}` : new Date(value).toLocaleString()
}

const refreshTimeRanges = [
  ['all', '全部作品'],
  ['week', '最近一周'],
  ['month', '最近一个月'],
  ['quarter', '最近三个月'],
  ['half_year', '最近半年'],
  ['year', '最近一年'],
]

function refreshRangeLabel(value) {
  return refreshTimeRanges.find(([key]) => key === value)?.[1] || '全部作品'
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem(tokenKey) || '')
  const [page, setPage] = useState('profiles')
  const [profileUrl, setProfileUrl] = useState('')
  const [profiles, setProfiles] = useState([])
  const [profile, setProfile] = useState(null)
  const [posts, setPosts] = useState([])
  const [filter, setFilter] = useState('all')
  const [selectedPosts, setSelectedPosts] = useState([])
  const [refresh, setRefresh] = useState(null)
  const [refreshTimeRange, setRefreshTimeRange] = useState('all')
  const [refreshItems, setRefreshItems] = useState([])
  const [selectedRefreshItems, setSelectedRefreshItems] = useState([])
  const [job, setJob] = useState(null)
  const [jobs, setJobs] = useState([])
  const [error, setError] = useState('')

  const visiblePosts = useMemo(() => posts, [posts])
  const selectedFailed = selectedPosts.filter(id => posts.find(post => post.aweme_id === id)?.download_status === 'failed')

  async function loadProfiles() {
    if (!token) return
    try { setProfiles(await api('/api/profiles')) } catch (err) { setError(err.message) }
  }

  async function loadJobs() {
    if (!token) return
    try { setJobs(await api('/api/jobs?limit=100')) } catch (err) { setError(err.message) }
  }

  async function cancelManagedJob(jobId) {
    try {
      await api(`/api/jobs/${jobId}/cancel`, { method: 'POST' })
      await loadJobs()
    } catch (err) { setError(err.message) }
  }

  async function deleteManagedJob(item) {
    if (['queued', 'enumerating', 'downloading'].includes(item.status)) {
      await cancelManagedJob(item.job_id)
      return
    }
    try {
      await api(`/api/jobs/${item.job_id}`, { method: 'DELETE' })
      await loadJobs()
      if (job?.job_id === item.job_id) setJob(null)
    } catch (err) { setError(err.message) }
  }

  async function openProfile(item) {
    setError('')
    try {
      const next = await api(`/api/profiles/${item.id}`)
      setProfile(next)
      setSelectedPosts([])
      setPosts(await api(`/api/profiles/${item.id}/posts?status=${filter}`))
      if (next.pending_refresh_id) {
        const pending = await api(`/api/profiles/${item.id}/refreshes/${next.pending_refresh_id}`)
        setRefresh(pending)
        setRefreshTimeRange(pending.time_range || 'all')
        setRefreshItems(await api(`/api/profiles/${item.id}/refreshes/${next.pending_refresh_id}/items`))
      } else {
        setRefresh(null)
        setRefreshItems([])
      }
    } catch (err) { setError(err.message) }
  }

  async function addProfile() {
    setError('')
    try {
      const next = await api('/api/profiles', { method: 'POST', body: JSON.stringify({ source_url: profileUrl }) })
      setProfileUrl('')
      await loadProfiles()
      await openProfile(next)
    } catch (err) { setError(err.message) }
  }

  async function refreshProfile() {
    if (!profile) return
    setError('')
    try {
      const next = await api(`/api/profiles/${profile.id}/refresh`, { method: 'POST', body: JSON.stringify({ max_items: 0, time_range: refreshTimeRange }) })
      setRefresh(next)
      setRefreshItems([])
      setSelectedRefreshItems([])
    } catch (err) { setError(err.message) }
  }

  async function applyRefresh() {
    if (!profile || !refresh) return
    try {
      await api(`/api/profiles/${profile.id}/refreshes/${refresh.id}/apply`, { method: 'POST', body: JSON.stringify({ selected_aweme_ids: selectedRefreshItems }) })
      setRefresh(null)
      await openProfile(profile)
      await loadProfiles()
    } catch (err) { setError(err.message) }
  }

  async function downloadSelected() {
    if (!profile || selectedPosts.length === 0) return
    try {
      const created = await api(`/api/profiles/${profile.id}/downloads`, { method: 'POST', body: JSON.stringify({ aweme_ids: selectedPosts }) })
      setJob({ job_id: created.job_id, status: created.status })
      setSelectedPosts([])
    } catch (err) { setError(err.message) }
  }

  async function retrySelected() {
    if (!profile || selectedFailed.length === 0) return
    try {
      const created = await api(`/api/profiles/${profile.id}/posts/retry`, { method: 'POST', body: JSON.stringify({ aweme_ids: selectedFailed }) })
      setJob({ job_id: created.job_id, status: created.status })
      setSelectedPosts([])
    } catch (err) { setError(err.message) }
  }

  async function cancelJob() {
    if (!job?.job_id) return
    try { await api(`/api/jobs/${job.job_id}/cancel`, { method: 'POST' }) } catch (err) { setError(err.message) }
  }

  useEffect(() => { loadProfiles(); loadJobs() }, [token])

  useEffect(() => {
    if (!token || page !== 'tasks') return undefined
    loadJobs()
    const timer = setInterval(loadJobs, 1000)
    return () => clearInterval(timer)
  }, [token, page])

  useEffect(() => {
    if (!profile) return
    api(`/api/profiles/${profile.id}/posts?status=${filter}`).then(setPosts).catch(err => setError(err.message))
  }, [profile?.id, filter])

  useEffect(() => {
    if (!refresh?.id || !profile) return undefined
    let stopped = false
    let profileNameLoaded = Boolean(profile.display_name)
    const poll = async () => {
      try {
        const next = await api(`/api/profiles/${profile.id}/refreshes/${refresh.id}`)
        if (stopped) return
        setRefresh(next)
        if (next.status === 'pending_confirmation') {
          setRefreshItems(await api(`/api/profiles/${profile.id}/refreshes/${refresh.id}/items`))
          if (!profileNameLoaded) {
            const updatedProfile = await api(`/api/profiles/${profile.id}`)
            if (!stopped) setProfile(updatedProfile)
            profileNameLoaded = true
          }
        }
        if (next.status === 'failed') setError(next.error || '主页更新失败')
      } catch (err) { if (!stopped) setError(err.message) }
    }
    poll()
    const timer = setInterval(poll, 1000)
    return () => { stopped = true; clearInterval(timer) }
  }, [refresh?.id, profile?.id])

  useEffect(() => {
    if (!job?.job_id) return undefined
    const controller = new AbortController()
    async function stream() {
      try {
        const response = await fetch(`/api/jobs/${job.job_id}/events`, { headers: authHeaders(), signal: controller.signal })
        if (!response.ok) throw new Error(await response.text())
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const events = buffer.split('\n\n')
          buffer = events.pop() || ''
          for (const event of events) {
            const line = event.split('\n').find(item => item.startsWith('data:'))
            if (line) setJob(JSON.parse(line.slice(5).trim()))
          }
        }
      } catch (err) { if (err.name !== 'AbortError') setError(err.message) }
      if (profile) api(`/api/profiles/${profile.id}/posts?status=${filter}`).then(setPosts).catch(() => {})
    }
    stream()
    return () => controller.abort()
  }, [job?.job_id])

  function saveToken(value) { setToken(value); localStorage.setItem(tokenKey, value) }
  function toggle(setter, id) { setter(values => values.includes(id) ? values.filter(value => value !== id) : [...values, id]) }

  return <main className="page">
    <header><h1>抖音主页作品管理</h1><p>主页发现、人工确认、下载状态、失败重试和文件管理集中在一个页面。</p></header>
    <section className="card auth"><label>管理员 Token<input type="password" value={token} onChange={event => saveToken(event.target.value)} placeholder="Bearer token" /></label></section>
    {error && <section className="error">{error}</section>}
    <nav className="card nav-tabs"><button className={page === 'profiles' ? 'active' : ''} onClick={() => setPage('profiles')}>主页作品管理</button><button className={page === 'tasks' ? 'active' : ''} onClick={() => setPage('tasks')}>后台任务管理</button></nav>
    {page === 'tasks' ? <section className="card task-admin"><div className="toolbar"><div><h2>后台任务</h2><small>进行中的任务每秒刷新；停止只会在当前作品完成或失败后生效。</small></div><button className="secondary" onClick={loadJobs}>立即刷新</button></div><div className="table-wrap"><table><thead><tr><th>任务</th><th>来源</th><th>状态</th><th>进度</th><th>当前项目</th><th>创建 / 更新</th><th>操作</th></tr></thead><tbody>{jobs.map(item => { const running = ['queued', 'enumerating', 'downloading'].includes(item.status); const label = item.kind === 'refresh' ? '主页更新' : '视频下载'; const source = item.display_name || item.sec_user_id || '单视频'; return <tr key={item.job_id}><td><strong>{label}</strong><small>{item.job_id}</small></td><td>{source}</td><td><span className={`status status-${item.status}`}>{item.status}</span>{item.error && <small>{item.error}</small>}</td><td>发现 {item.discovered} · 完成 {item.completed} · 跳过 {item.skipped} · 失败 {item.failed}</td><td>{item.current_item ? <>{item.current_item.title || item.current_item.aweme_id}<small>{item.current_item.percent ?? 0}% {item.current_item.speed || ''} {item.current_item.eta ? `ETA ${item.current_item.eta}` : ''}</small></> : '—'}</td><td>{formatDate(item.created_at)}<small>{formatDate(item.updated_at)}</small></td><td><button className="secondary" onClick={() => running ? cancelManagedJob(item.job_id) : deleteManagedJob(item)}>{running ? '停止' : '删除'}</button></td></tr> })}</tbody></table></div>{jobs.length === 0 && <p className="empty">暂无后台任务</p>}</section> : <>
    <section className="card">
      <h2>我的主页</h2>
      <div className="inline-form"><input value={profileUrl} onChange={event => setProfileUrl(event.target.value)} placeholder="https://www.douyin.com/user/..." /><button onClick={addProfile} disabled={!profileUrl || !token}>添加主页</button></div>
      <div className="profile-grid">{profiles.map(item => <button key={item.id} className={`profile-card ${profile?.id === item.id ? 'selected' : ''}`} onClick={() => openProfile(item)}><strong title={item.display_name || item.sec_user_id}>{item.display_name || item.sec_user_id}</strong><small title={item.sec_user_id}>{item.sec_user_id}</small><span title={`作品 ${item.post_count} · 已下载 ${item.downloaded_count} · 失败 ${item.failed_count} · 跳过 ${item.skipped_count}`}>作品 {item.post_count} · 已下载 {item.downloaded_count} · 失败 {item.failed_count} · 跳过 {item.skipped_count}</span><small>上次更新：{formatDate(item.last_refresh_at)}</small></button>)}</div>
    </section>
    {profile && <>
      <section className="card toolbar"><div><h2>{profile.display_name || profile.sec_user_id}</h2><small>{profile.profile_url}</small></div><label className="refresh-range">更新范围<select value={refreshTimeRange} onChange={event => setRefreshTimeRange(event.target.value)} disabled={refresh && ['queued', 'enumerating', 'pending_confirmation'].includes(refresh.status)}>{refreshTimeRanges.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><button onClick={refreshProfile} disabled={refresh && ['queued', 'enumerating', 'pending_confirmation'].includes(refresh.status)}>{refresh?.status === 'pending_confirmation' ? '有待确认更新' : '更新主页'}</button><button className="secondary" onClick={() => { if (window.confirm('只删除主页管理记录，不删除视频文件，确定吗？')) api(`/api/profiles/${profile.id}`, { method: 'DELETE' }).then(() => { setProfile(null); loadProfiles() }).catch(err => setError(err.message)) }}>删除管理记录</button></section>
      {refresh && <section className="card"><div className="toolbar"><h2>更新发现结果</h2><span className="badge">{refresh.status}</span></div><p>范围：{refreshRangeLabel(refresh.time_range)}；发现 {refresh.discovered_count}，新增 {refresh.new_count}，变化 {refresh.changed_count}，消失 {refresh.missing_count}，跳过 {refresh.skipped_count}</p>{refresh.status === 'pending_confirmation' && <><div className="actions"><button onClick={() => setSelectedRefreshItems(refreshItems.filter(item => ['new', 'metadata_changed'].includes(item.change_type) && !['image', 'unknown', 'remote_missing'].includes(item.change_type)).map(item => item.aweme_id))}>全选可下载</button><button className="secondary" onClick={applyRefresh}>确认选中更新（{selectedRefreshItems.length}）</button></div><div className="table-wrap"><table><thead><tr><th>选</th><th>作品</th><th>日期</th><th>变化</th><th>原因</th></tr></thead><tbody>{refreshItems.map(item => <tr key={item.aweme_id}><td><input type="checkbox" checked={selectedRefreshItems.includes(item.aweme_id)} onChange={() => toggle(setSelectedRefreshItems, item.aweme_id)} /></td><td>{item.title || item.aweme_id}<small>{item.aweme_id}</small></td><td>{formatDate(item.upload_date)}</td><td>{item.change_type}</td><td>{item.skip_reason || '—'}</td></tr>)}</tbody></table></div></>}</section>}
      <section className="card"><div className="toolbar"><div><h2>作品清单</h2><small>已下载状态以应用数据库为准</small></div><select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">全部</option><option value="not_downloaded">未下载</option><option value="downloaded">已下载</option><option value="failed">失败</option><option value="skipped">跳过</option><option value="remote_missing">远端已消失</option></select></div><div className="actions"><button onClick={downloadSelected} disabled={!selectedPosts.length}>下载选中（{selectedPosts.length}）</button><button className="secondary" onClick={retrySelected} disabled={!selectedFailed.length}>重试失败（{selectedFailed.length}）</button><button className="secondary" onClick={() => setSelectedPosts(visiblePosts.map(post => post.aweme_id))}>全选当前</button></div><div className="table-wrap"><table><thead><tr><th>选</th><th>标题 / ID</th><th>日期</th><th>状态</th><th>文件</th><th>错误 / 跳过原因</th><th>尝试</th></tr></thead><tbody>{visiblePosts.map(post => <tr key={post.aweme_id}><td><input type="checkbox" checked={selectedPosts.includes(post.aweme_id)} onChange={() => toggle(setSelectedPosts, post.aweme_id)} /></td><td>{post.title || '无标题'}<small>{post.aweme_id}</small></td><td>{formatDate(post.upload_date)}</td><td><span className={`status status-${post.download_status}`}>{post.remote_state === 'remote_missing' ? 'remote_missing' : post.download_status}{post.download_status === 'downloaded' && !post.file_exists ? '（文件缺失）' : ''}</span></td><td>{post.download_file || '—'}</td><td>{post.last_error_message || post.skip_reason_message || '—'}</td><td>{post.attempt_count}</td></tr>)}</tbody></table></div></section>
      {job && <section className="card"><div className="toolbar"><h2>当前任务</h2><button className="secondary" onClick={cancelJob} disabled={['completed', 'completed_with_errors', 'failed', 'cancelled'].includes(job.status)}>取消</button></div><div className="stats"><span>状态：{job.status}</span><span>完成：{job.completed}</span><span>跳过：{job.skipped}</span><span>失败：{job.failed}</span></div>{job.current_item && <div className="current"><strong>{job.current_item.title || job.current_item.aweme_id}</strong><progress max="100" value={Number(job.current_item.percent || 0)} /><small>{job.current_item.percent || 0}% {job.current_item.speed || ''} {job.current_item.eta ? `ETA ${job.current_item.eta}` : ''}</small></div>}</section>}
    </>}
    </>}
  </main>
}
