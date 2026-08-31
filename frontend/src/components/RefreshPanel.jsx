import { CheckCircleOutlined, LoadingOutlined, WarningOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Col, Empty, Progress, Row, Space, Spin, Statistic, Table, Tag, Typography } from 'antd'
import { changeTypeLabel, formatDate, refreshRangeLabel, statusLabel } from './utils'

const selectableChangeTypes = ['new', 'metadata_changed']
const blockedChangeTypes = ['image', 'unknown', 'remote_missing']

export default function RefreshPanel({ refresh, refreshItems, selectedRefreshItems, setSelectedRefreshItems, onApply, loading }) {
  if (!refresh) return null
  const isPending = refresh.status === 'pending_confirmation'
  const isActive = ['queued', 'enumerating'].includes(refresh.status)
  const isFailed = refresh.status === 'failed'
  const rowSelection = isPending ? {
    selectedRowKeys: selectedRefreshItems,
    onChange: setSelectedRefreshItems,
    getCheckboxProps: record => ({ disabled: !selectableChangeTypes.includes(record.change_type) || blockedChangeTypes.includes(record.change_type) }),
  } : undefined
  const columns = [
    { title: '作品', key: 'title', render: (_, item) => <Space orientation="vertical" size={0}><Typography.Text strong ellipsis={{ tooltip: item.title || item.aweme_id }}>{item.title || '无标题'}</Typography.Text><Typography.Text type="secondary" copyable={{ text: item.aweme_id }}>{item.aweme_id}</Typography.Text></Space> },
    { title: '日期', dataIndex: 'upload_date', key: 'upload_date', render: formatDate },
    { title: '变化', dataIndex: 'change_type', key: 'change_type', render: value => <Tag color={value === 'new' ? 'green' : value === 'metadata_changed' ? 'blue' : 'default'}>{changeTypeLabel(value)}</Tag> },
    { title: '原因', dataIndex: 'skip_reason', key: 'skip_reason', render: value => value || '—' },
  ]
  const discovered = refresh.discovered_count || 0
  const progress = isActive && discovered > 0 ? Math.min(96, 20 + Math.round((refresh.new_count + refresh.changed_count + refresh.missing_count) / discovered * 70)) : 0
  return <Card className="panel-card" title={<Space><span>更新发现结果</span><Tag color={isPending ? 'gold' : isFailed ? 'red' : isActive ? 'processing' : 'green'} icon={isActive ? <LoadingOutlined /> : isFailed ? <WarningOutlined /> : <CheckCircleOutlined />}>{statusLabel(refresh.status)}</Tag></Space>}>
    <Row gutter={[16, 16]} className="stat-row"><Col xs={12} md={6}><Statistic title="发现" value={refresh.discovered_count} /></Col><Col xs={12} md={6}><Statistic title="新增" value={refresh.new_count} valueStyle={{ color: '#389e0d' }} /></Col><Col xs={12} md={6}><Statistic title="信息变化" value={refresh.changed_count} valueStyle={{ color: '#1677ff' }} /></Col><Col xs={12} md={6}><Statistic title="远端消失 / 跳过" value={`${refresh.missing_count} / ${refresh.skipped_count}`} /></Col></Row>
    <Typography.Paragraph type="secondary" className="panel-meta">范围：{refreshRangeLabel(refresh.time_range)}</Typography.Paragraph>
    {isActive && <div className="progress-block"><Spin indicator={<LoadingOutlined spin />} /><Typography.Text>正在分页发现作品，请稍候...</Typography.Text>{discovered > 0 && <Progress percent={progress} status="active" showInfo={false} />}</div>}
    {isFailed && <Alert type="error" showIcon title="主页更新失败" description={refresh.error || '请检查 Cookie、请求频率或平台风控状态。'} />}
    {isPending && <><Alert className="panel-alert" type="info" showIcon title="发现结果需要人工确认" description="只有勾选并确认的作品才会应用到当前清单。图集和未知类型不能下载。" /><div className="panel-actions"><Typography.Text type="secondary">已选择 {selectedRefreshItems.length} 项</Typography.Text><Space wrap><Button type="link" onClick={() => setSelectedRefreshItems(refreshItems.filter(item => selectableChangeTypes.includes(item.change_type) && !blockedChangeTypes.includes(item.change_type)).map(item => item.aweme_id))}>全选可下载</Button><Button type="primary" icon={<CheckCircleOutlined />} loading={loading} disabled={!selectedRefreshItems.length} onClick={onApply}>确认应用（{selectedRefreshItems.length}）</Button></Space></div><Table rowKey="aweme_id" rowSelection={rowSelection} columns={columns} dataSource={refreshItems} size="middle" pagination={{ pageSize: 10, hideOnSinglePage: true }} locale={{ emptyText: <Empty description="没有待确认的变化" /> }} scroll={{ x: 720 }} /></>}
  </Card>
}
