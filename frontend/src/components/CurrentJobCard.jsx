import { StopOutlined } from '@ant-design/icons'
import { Button, Card, Col, Descriptions, Progress, Row, Space, Statistic, Tag, Typography } from 'antd'
import { statusLabel } from './utils'

export default function CurrentJobCard({ job, onCancel, loading }) {
  if (!job) return null
  const percent = Number(job.current_item?.percent || 0)
  const cancellable = !['completed', 'completed_with_errors', 'failed', 'cancelled'].includes(job.status)
  return <Card className="panel-card" title={<Space><span>当前任务</span><Tag color={cancellable ? 'processing' : 'default'}>{statusLabel(job.status)}</Tag></Space>} extra={<Button danger type="text" icon={<StopOutlined />} onClick={onCancel} loading={loading} disabled={!cancellable}>取消任务</Button>}>
    <Row gutter={[16, 16]} className="stat-row"><Col xs={12} md={6}><Statistic title="发现" value={job.discovered} /></Col><Col xs={12} md={6}><Statistic title="完成" value={job.completed} valueStyle={{ color: '#389e0d' }} /></Col><Col xs={12} md={6}><Statistic title="跳过" value={job.skipped} /></Col><Col xs={12} md={6}><Statistic title="失败" value={job.failed} valueStyle={{ color: job.failed ? '#cf1322' : undefined }} /></Col></Row>
    {job.current_item && <div className="current-job"><Typography.Text strong ellipsis={{ tooltip: job.current_item.title || job.current_item.aweme_id }}>{job.current_item.title || job.current_item.aweme_id}</Typography.Text><Progress percent={percent} status={job.current_item.status === 'failed' ? 'exception' : 'active'} /><Typography.Text type="secondary">{percent}% {job.current_item.speed || ''} {job.current_item.eta ? `ETA ${job.current_item.eta}` : ''}</Typography.Text></div>}
    {job.error && <Descriptions size="small" column={1} items={[{ key: 'error', label: '错误', children: job.error }]} />}
  </Card>
}
