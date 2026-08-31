import { CloudDownloadOutlined, DatabaseOutlined, MoreOutlined, ReloadOutlined, SyncOutlined } from '@ant-design/icons'
import { Button, Dropdown, Empty, Image, Select, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { formatDate, statusLabel } from './utils'

function postStatus(post) {
  if (post.remote_state === 'remote_missing') return <Tag color="default">远端已消失</Tag>
  if (post.download_status === 'downloaded' && !post.file_exists) return <Tag color="warning">已下载但文件缺失</Tag>
  const color = { downloaded: 'success', failed: 'error', skipped: 'warning', downloading: 'processing' }[post.download_status]
  return <Tag color={color}>{statusLabel(post.download_status)}</Tag>
}

function trunc(value, rows = 2) {
  if (!value) return '—'
  return <Typography.Paragraph className="table-text" ellipsis={{ rows, tooltip: value }}>{value}</Typography.Paragraph>
}

export default function PostsTable({ posts, profile, thumbnailUrls, selectedPosts, setSelectedPosts, filter, setFilter, onDownload, onRetry, onMetadata, onRetryMetadata, busy }) {
  const selectedFailed = selectedPosts.filter(id => posts.find(post => post.aweme_id === id)?.download_status === 'failed')
  const selectedMetadataFailed = selectedPosts.filter(id => posts.find(post => post.aweme_id === id)?.metadata_error_code)
  const columns = [
    { title: '标题 / ID', key: 'title', width: 260, render: (_, post) => <Space align="start" size={10}>{thumbnailUrls[post.aweme_id] ? <Image className="post-thumb" width={44} height={64} src={thumbnailUrls[post.aweme_id]} preview={{ mask: '预览' }} /> : <div className="post-thumb-placeholder">视频</div>}<Space orientation="vertical" size={1} className="table-primary"><Typography.Text strong ellipsis={{ tooltip: post.title || '无标题' }}>{post.title || '无标题'}</Typography.Text><Typography.Text type="secondary" copyable={{ text: post.aweme_id }}>{post.aweme_id}</Typography.Text><Typography.Text type="secondary">{post.channel || profile.display_name || '—'}</Typography.Text></Space></Space> },
    { title: '日期 / 时长', key: 'date', width: 140, render: (_, post) => <Space orientation="vertical" size={1}><span>{formatDate(post.upload_date)}</span><Typography.Text type="secondary">{post.duration ? `${Math.round(post.duration)} 秒` : '—'}</Typography.Text></Space> },
    { title: '状态', key: 'status', width: 150, render: (_, post) => <Space orientation="vertical" size={2}>{postStatus(post)}<Typography.Text type="secondary">{post.season_number != null ? `S${String(post.season_number).padStart(4, '0')}E${String(post.episode_number || 0).padStart(4, '0')}` : '未分配集号'}</Typography.Text></Space> },
    { title: '互动统计', key: 'stats', width: 160, render: (_, post) => <Space orientation="vertical" size={1}><span>播放 {post.view_count ?? '—'}</span><Typography.Text type="secondary">赞 {post.like_count ?? '—'} · 评 {post.comment_count ?? '—'}</Typography.Text><Typography.Text type="secondary">分享 {post.repost_count ?? '—'} · 藏 {post.save_count ?? '—'}</Typography.Text></Space> },
    { title: '媒体 / NFO', key: 'media', width: 220, render: (_, post) => <Space orientation="vertical" size={1}>{trunc(post.media_file || post.download_file, 2)}<Typography.Text type="secondary">{post.nfo_file ? `NFO：${post.nfo_file}` : '尚未生成 NFO'}</Typography.Text></Space> },
    { title: '错误 / 跳过原因', key: 'error', width: 240, render: (_, post) => { const value = post.metadata_error_message || post.artwork_error_message || post.last_error_message || post.skip_reason_message; return <Tooltip title={value}><Typography.Text type="secondary">{trunc(value, 3)}</Typography.Text></Tooltip> } },
    { title: '尝试', dataIndex: 'attempt_count', key: 'attempt_count', width: 70 },
  ]
  const menuItems = [
    { key: 'retry', label: `重试失败${selectedFailed.length ? `（${selectedFailed.length}）` : ''}`, icon: <ReloadOutlined />, disabled: !selectedFailed.length, onClick: onRetry },
    { key: 'metadata-all', label: '刷新全部元数据', icon: <DatabaseOutlined />, disabled: Boolean(selectedPosts.length), onClick: () => onMetadata() },
    { key: 'metadata-selected', label: `刷新选中元数据${selectedPosts.length ? `（${selectedPosts.length}）` : ''}`, icon: <SyncOutlined />, disabled: !selectedPosts.length, onClick: () => onMetadata(selectedPosts) },
    { key: 'metadata-retry', label: `重试元数据失败${selectedMetadataFailed.length ? `（${selectedMetadataFailed.length}）` : ''}`, icon: <ReloadOutlined />, disabled: !selectedMetadataFailed.length, onClick: onRetryMetadata },
    { key: 'select-all', label: '全选当前', onClick: () => setSelectedPosts(posts.map(post => post.aweme_id)) },
  ]
  const filterOptions = [['all', '全部'], ['not_downloaded', '未下载'], ['downloaded', '已下载'], ['failed', '失败'], ['skipped', '跳过'], ['remote_missing', '远端已消失']].map(([value, label]) => ({ value, label }))
  return <div className="table-panel"><div className="table-toolbar"><Space orientation="vertical" size={2}><Typography.Title level={4} className="section-title">作品清单</Typography.Title><Typography.Text type="secondary">已下载状态以应用数据库为准，互动数据需要手动刷新</Typography.Text></Space><Select value={filter} onChange={setFilter} options={filterOptions} /></div><div className="action-bar"><Space wrap><Button type="primary" icon={<CloudDownloadOutlined />} loading={busy === 'download'} disabled={!selectedPosts.length} onClick={onDownload}>下载选中（{selectedPosts.length}）</Button><Dropdown menu={{ items: menuItems }} trigger={['click']}><Button icon={<MoreOutlined />}>更多操作</Button></Dropdown></Space><Typography.Text type="secondary">已选择 {selectedPosts.length} 项</Typography.Text></div><Table rowKey="aweme_id" rowSelection={{ selectedRowKeys: selectedPosts, onChange: setSelectedPosts }} columns={columns} dataSource={posts} size="middle" loading={busy === 'posts'} pagination={{ pageSize: 12, showSizeChanger: true, pageSizeOptions: [12, 24, 48] }} locale={{ emptyText: <Empty description="暂无符合条件的作品" /> }} scroll={{ x: 1240 }} /></div>
}
