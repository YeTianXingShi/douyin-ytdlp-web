export const refreshTimeRanges = [
  ['all', '全部作品'],
  ['week', '最近一周'],
  ['month', '最近一个月'],
  ['quarter', '最近三个月'],
  ['half_year', '最近半年'],
  ['year', '最近一年'],
]

export function formatDate(value) {
  if (!value) return '—'
  return value.length === 8 ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}` : new Date(value).toLocaleString()
}

export function refreshRangeLabel(value) {
  return refreshTimeRanges.find(([key]) => key === value)?.[1] || '全部作品'
}

export const activeJobStatuses = ['queued', 'enumerating', 'downloading', 'processing']

export function statusLabel(value) {
  return {
    downloaded: '已下载', failed: '失败', skipped: '已跳过', already_downloaded: '已存在', downloading: '下载中',
    queued: '排队中', enumerating: '发现作品', processing: '处理中', completed: '已完成',
    completed_with_errors: '完成但有错误', cancelled: '已取消', pending_confirmation: '待确认', remote_missing: '远端已消失',
  }[value] || value || '未知'
}

export function changeTypeLabel(value) {
  return { new: '新增', metadata_changed: '信息变化', missing: '远端消失', image: '图集', unknown: '未知类型', remote_missing: '远端消失' }[value] || value || '无变化'
}
