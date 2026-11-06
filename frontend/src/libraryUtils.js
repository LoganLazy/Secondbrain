// 页面内来回阅读时保留列表/已完成搜索；不写入浏览器持久存储，不自动重复在线搜索。
export const libraryViews = new Map()

export function searchSnippet(value, query, size = 280) {
  const text = String(value || '')
  const terms = [...new Set(String(query || '').trim().split(/\s+/u).filter(Boolean))]
    .slice(0, 16).sort((a, b) => b.length - a.length)
  if (!terms.length) return [{text: text.slice(0, size) + (text.length > size ? '…' : ''), hit: false}]
  const escaped = terms.map(term => Array.from(term).map(char =>
    '\\^$.*+?()[]{}|'.includes(char) ? '\\' + char : char).join(''))
  const pattern = new RegExp(escaped.join('|'), 'giu')
  const first = pattern.exec(text)
  const start = Math.max(0, (first?.index || 0) - 50)
  const body = text.slice(start, start + size)
  pattern.lastIndex = 0
  const parts = start ? [{text:'…', hit:false}] : []
  let match, cursor = 0
  while ((match = pattern.exec(body))) {
    if (match.index > cursor) parts.push({text:body.slice(cursor, match.index), hit:false})
    parts.push({text:match[0], hit:true})
    cursor = match.index + match[0].length
  }
  if (cursor < body.length) parts.push({text:body.slice(cursor), hit:false})
  if (start + body.length < text.length) parts.push({text:'…', hit:false})
  return parts
}
