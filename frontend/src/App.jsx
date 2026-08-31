import { useEffect, useState } from 'react'
import { App as AntApp, Alert, Badge, Button, ConfigProvider, Input, Layout, Menu, Popover, Space, Typography } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { AppstoreOutlined, KeyOutlined, ProfileOutlined, UnorderedListOutlined } from '@ant-design/icons'
import ProfileWorkspace from './components/ProfileWorkspace'
import TaskAdmin from './components/TaskAdmin'

const { Header, Content } = Layout
const tokenKey = 'douyin-admin-token'

function authHeaders() {
  const token = localStorage.getItem(tokenKey) || ''
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(options.headers || {}) } })
  if (!response.ok) throw new Error(await response.text())
  return response.status === 204 ? null : response.json()
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
  const [thumbnailUrls, setThumbnailUrls] = useState({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')

  async function runBusy(name, action) {
    setBusy(name)
    try { return await action() } catch (err) { setError(err.message) } finally { setBusy('') }
  }

  async function loadProfiles() { if (!token) return; try { setProfiles(await api('/api/profiles')) } catch (err) { setError(err.message) } }
  async function loadJobs() { if (!token) return; try { setJobs(await api('/api/jobs?limit=100')) } catch (err) { setError(err.message) } }

  async function openProfile(item) {
    setError('')
    await runBusy('profile', async () => {
      const next = await api(`/api/profiles/${item.id}`)
      setProfile(next); setSelectedPosts([]); setPosts(await api(`/api/profiles/${item.id}/posts?status=${filter}`))
      if (next.pending_refresh_id) {
        const pending = await api(`/api/profiles/${item.id}/refreshes/${next.pending_refresh_id}`)
        setRefresh(pending); setRefreshTimeRange(pending.time_range || 'all'); setRefreshItems(await api(`/api/profiles/${item.id}/refreshes/${next.pending_refresh_id}/items`))
      } else { setRefresh(null); setRefreshItems([]) }
    })
  }

  async function addProfile() { if (!profileUrl || !token) return; setError(''); await runBusy('add-profile', async () => { const next = await api('/api/profiles', { method: 'POST', body: JSON.stringify({ source_url: profileUrl }) }); setProfileUrl(''); await loadProfiles(); await openProfile(next) }) }
  async function refreshProfile() { if (!profile) return; setError(''); await runBusy('refresh-profile', async () => { const next = await api(`/api/profiles/${profile.id}/refresh`, { method: 'POST', body: JSON.stringify({ max_items: 0, time_range: refreshTimeRange }) }); setRefresh(next); setRefreshItems([]); setSelectedRefreshItems([]) }) }
  async function applyRefresh() { if (!profile || !refresh) return; await runBusy('apply-refresh', async () => { await api(`/api/profiles/${profile.id}/refreshes/${refresh.id}/apply`, { method: 'POST', body: JSON.stringify({ selected_aweme_ids: selectedRefreshItems }) }); setRefresh(null); await openProfile(profile); await loadProfiles() }) }
  async function deleteProfile() { if (!profile) return; await runBusy('delete-profile', async () => { await api(`/api/profiles/${profile.id}`, { method: 'DELETE' }); setProfile(null); await loadProfiles() }) }

  async function createJob(path, awemeIds) { const created = await api(path, { method: 'POST', body: JSON.stringify({ aweme_ids: awemeIds }) }); setJob({ job_id: created.job_id, status: created.status }); setSelectedPosts([]) }
  async function downloadSelected() { if (!profile || !selectedPosts.length) return; await runBusy('download', () => createJob(`/api/profiles/${profile.id}/downloads`, selectedPosts)) }
  async function retrySelected() { const ids = selectedPosts.filter(id => posts.find(post => post.aweme_id === id)?.download_status === 'failed'); if (!profile || !ids.length) return; await runBusy('retry', () => createJob(`/api/profiles/${profile.id}/posts/retry`, ids)) }
  async function refreshMetadata(ids = selectedPosts) { if (!profile) return; await runBusy('metadata', () => createJob(`/api/profiles/${profile.id}/metadata-refresh`, ids)) }
  async function retryMetadata() { const ids = selectedPosts.filter(id => posts.find(post => post.aweme_id === id)?.metadata_error_code); if (!profile || !ids.length) return; await runBusy('metadata-retry', () => createJob(`/api/profiles/${profile.id}/metadata-refresh/retry`, ids)) }
  async function cancelJob() { if (!job?.job_id) return; await runBusy('cancel-job', () => api(`/api/jobs/${job.job_id}/cancel`, { method: 'POST' })) }
  async function cancelManagedJob(jobId) { await runBusy(jobId, async () => { await api(`/api/jobs/${jobId}/cancel`, { method: 'POST' }); await loadJobs() }) }
  async function deleteManagedJob(item) { if (['queued', 'enumerating', 'downloading'].includes(item.status)) return cancelManagedJob(item.job_id); await runBusy(item.job_id, async () => { await api(`/api/jobs/${item.job_id}`, { method: 'DELETE' }); await loadJobs(); if (job?.job_id === item.job_id) setJob(null) }) }

  useEffect(() => { loadProfiles(); loadJobs() }, [token])
  useEffect(() => { if (!token || page !== 'tasks') return undefined; loadJobs(); const timer = setInterval(loadJobs, 1000); return () => clearInterval(timer) }, [token, page])
  useEffect(() => { if (!profile) return; api(`/api/profiles/${profile.id}/posts?status=${filter}`).then(setPosts).catch(err => setError(err.message)) }, [profile?.id, filter])
  useEffect(() => {
    if (!profile?.id || !token) { setThumbnailUrls({}); return undefined }
    let stopped = false; const objectUrls = []
    async function loadThumbnails() {
      const entries = await Promise.all(posts.filter(post => post.thumbnail_file).map(async post => { try { const response = await fetch(`/api/profiles/${profile.id}/files/${post.thumbnail_file}`, { headers: authHeaders() }); if (!response.ok) return [post.aweme_id, null]; const objectUrl = URL.createObjectURL(await response.blob()); objectUrls.push(objectUrl); return [post.aweme_id, objectUrl] } catch { return [post.aweme_id, null] } }))
      if (!stopped) setThumbnailUrls(Object.fromEntries(entries.filter(([, url]) => url)))
    }
    loadThumbnails(); return () => { stopped = true; objectUrls.forEach(objectUrl => URL.revokeObjectURL(objectUrl)) }
  }, [profile?.id, posts, token])
  useEffect(() => {
    if (!refresh?.id || !profile) return undefined
    let stopped = false; let profileNameLoaded = Boolean(profile.display_name)
    const poll = async () => { try { const next = await api(`/api/profiles/${profile.id}/refreshes/${refresh.id}`); if (stopped) return; setRefresh(next); if (next.status === 'pending_confirmation') { setRefreshItems(await api(`/api/profiles/${profile.id}/refreshes/${refresh.id}/items`)); if (!profileNameLoaded) { const updatedProfile = await api(`/api/profiles/${profile.id}`); if (!stopped) setProfile(updatedProfile); profileNameLoaded = true } } if (next.status === 'failed') setError(next.error || '主页更新失败') } catch (err) { if (!stopped) setError(err.message) } }
    poll(); const timer = setInterval(poll, 1000); return () => { stopped = true; clearInterval(timer) }
  }, [refresh?.id, profile?.id])
  useEffect(() => {
    if (!job?.job_id) return undefined
    const controller = new AbortController()
    async function stream() { try { const response = await fetch(`/api/jobs/${job.job_id}/events`, { headers: authHeaders(), signal: controller.signal }); if (!response.ok) throw new Error(await response.text()); const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; while (true) { const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); const events = buffer.split('\n\n'); buffer = events.pop() || ''; for (const event of events) { const line = event.split('\n').find(item => item.startsWith('data:')); if (line) setJob(JSON.parse(line.slice(5).trim())) } } } catch (err) { if (err.name !== 'AbortError') setError(err.message) } if (profile) api(`/api/profiles/${profile.id}/posts?status=${filter}`).then(setPosts).catch(() => {}) }
    stream(); return () => controller.abort()
  }, [job?.job_id])

  function saveToken(value) { setToken(value); localStorage.setItem(tokenKey, value) }

  const authContent = <Space orientation="vertical" size={12} className="auth-popover"><Space orientation="vertical" size={2}><Typography.Text strong>管理员 Token</Typography.Text><Typography.Text type="secondary">用于访问主页、作品和后台任务数据。</Typography.Text></Space><Input.Password size="large" allowClear value={token} onChange={event => saveToken(event.target.value)} placeholder="输入管理员 Token" /><Alert showIcon type={token ? 'success' : 'warning'} title={token ? 'Token 已配置并自动保存' : '尚未配置 Token'} /></Space>
  return <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#1677ff', borderRadius: 8, controlHeight: 38, fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' }, components: { Layout: { headerBg: '#10233f' }, Menu: { itemBorderRadius: 6 } } }}><AntApp><Layout className="app-shell"><Header className="app-header"><div className="brand"><div className="brand-mark"><AppstoreOutlined /></div><div><Typography.Text className="brand-title">抖音作品库</Typography.Text><Typography.Text className="brand-subtitle">yt-dlp media workspace</Typography.Text></div></div><Popover trigger="click" placement="bottomRight" title="访问授权" content={authContent}><Button type="text" className="auth-trigger" icon={<KeyOutlined />}><Space size={8}><span>授权设置</span><Badge status={token ? 'success' : 'warning'} text={token ? '已配置' : '未配置'} /></Space></Button></Popover></Header><Content className="app-content"><div className="content-wrap"><Menu className="main-nav" mode="horizontal" selectedKeys={[page]} onClick={({ key }) => setPage(key)} items={[{ key: 'profiles', icon: <ProfileOutlined />, label: '主页作品管理' }, { key: 'tasks', icon: <UnorderedListOutlined />, label: '后台任务管理' }]} />{error && <Alert className="global-alert" type="error" showIcon closable onClose={() => setError('')} title={error} />}{page === 'tasks' ? <TaskAdmin jobs={jobs} onRefresh={loadJobs} onCancel={cancelManagedJob} onDelete={deleteManagedJob} loading={busy} /> : <ProfileWorkspace profiles={profiles} profile={profile} profileUrl={profileUrl} setProfileUrl={setProfileUrl} onAddProfile={addProfile} onOpenProfile={openProfile} onDeleteProfile={deleteProfile} onRefreshProfile={refreshProfile} refresh={refresh} refreshItems={refreshItems} selectedRefreshItems={selectedRefreshItems} setSelectedRefreshItems={setSelectedRefreshItems} onApplyRefresh={applyRefresh} refreshTimeRange={refreshTimeRange} setRefreshTimeRange={setRefreshTimeRange} posts={posts} thumbnailUrls={thumbnailUrls} selectedPosts={selectedPosts} setSelectedPosts={setSelectedPosts} filter={filter} setFilter={setFilter} onDownload={downloadSelected} onRetry={retrySelected} onMetadata={refreshMetadata} onRetryMetadata={retryMetadata} job={job} onCancelJob={cancelJob} busy={busy} />}</div></Content></Layout></AntApp></ConfigProvider>
}
