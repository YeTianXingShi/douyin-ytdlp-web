import { DeleteOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons'
import { Button, Card, Empty, Progress, Space, Table, Tag, Typography } from 'antd'
import { activeJobStatuses, formatDate, statusLabel } from './utils'

export default function TaskAdmin({ jobs, onRefresh, onCancel, onDelete, loading }) {
  const columns = [
    { title: '任务', key: 'task', width: 190, render: (_, item) => <Space orientation="vertical" size={1}><Typography.Text strong>{item.kind === 'refresh' ? '主页更新' : item.kind === 'metadata' ? '元数据刷新' : '视频下载'}</Typography.Text><Typography.Text type="secondary" copyable={{ text: item.job_id }}>{item.job_id}</Typography.Text></Space> },
    { title: '来源', key: 'source', render: (_, item) => item.display_name || item.sec_user_id || '单视频' },
    { title: '状态', dataIndex: 'status', key: 'status', render: value => <Tag color={value === 'failed' ? 'error' : activeJobStatuses.includes(value) ? 'processing' : value === 'completed' ? 'success' : 'default'}>{statusLabel(value)}</Tag> },
    { title: '进度', key: 'progress', width: 240, render: (_, item) => <Space orientation="vertical" size={2} className="task-progress"><Typography.Text type="secondary">发现 {item.discovered} · 完成 {item.completed} · 跳过 {item.skipped} · 失败 {item.failed}</Typography.Text>{item.current_item && <Progress percent={Number(item.current_item.percent || 0)} size="small" status={item.current_item.status === 'failed' ? 'exception' : 'active'} />}</Space> },
    { title: '当前项目', key: 'current', width: 220, render: (_, item) => item.current_item ? <Space orientation="vertical" size={1}><Typography.Text ellipsis={{ tooltip: item.current_item.title || item.current_item.aweme_id }}>{item.current_item.title || item.current_item.aweme_id}</Typography.Text><Typography.Text type="secondary">{item.current_item.speed || ''} {item.current_item.eta ? `ETA ${item.current_item.eta}` : ''}</Typography.Text></Space> : '—' },
    { title: '创建 / 更新', key: 'time', width: 180, render: (_, item) => <Space orientation="vertical" size={1}><span>{formatDate(item.created_at)}</span><Typography.Text type="secondary">{formatDate(item.updated_at)}</Typography.Text></Space> },
    { title: '操作', key: 'action', fixed: 'right', width: 100, render: (_, item) => activeJobStatuses.includes(item.status) ? <Button type="text" danger icon={<StopOutlined />} loading={loading === item.job_id} onClick={() => onCancel(item.job_id)}>停止</Button> : <Button type="text" danger icon={<DeleteOutlined />} loading={loading === item.job_id} onClick={() => onDelete(item)}>删除</Button> },
  ]
  return <Card className="panel-card" title={<Space><span>后台任务</span><Typography.Text type="secondary">{jobs.length} 条记录</Typography.Text></Space>} extra={<Button icon={<ReloadOutlined />} onClick={onRefresh} loading={loading === 'refresh'}>刷新</Button>}><Table rowKey="job_id" columns={columns} dataSource={jobs} size="middle" loading={loading === 'jobs'} pagination={{ pageSize: 12, showSizeChanger: false }} locale={{ emptyText: <Empty description="暂无后台任务" /> }} scroll={{ x: 1120 }} /></Card>
}
