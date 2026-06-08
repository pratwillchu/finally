'use client'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import type { Snapshot } from '@/types'

interface PnLChartProps {
  snapshots: Snapshot[]
}

function formatTime(ts: string): string {
  const d = new Date(ts + 'Z')
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

export default function PnLChart({ snapshots }: PnLChartProps) {
  if (snapshots.length < 2) {
    return (
      <div className="flex items-center justify-center h-full text-[#6e7681] font-mono text-xs">
        ACCUMULATING DATA...
      </div>
    )
  }

  const data = snapshots.map(s => ({ time: formatTime(s.recorded_at), value: s.total_value }))
  const baseline = snapshots[0].total_value
  const current = snapshots[snapshots.length - 1].total_value
  const change = current - baseline
  const isUp = change >= 0

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-3 py-1">
        <span className="text-[#8b949e] font-mono text-xs">PORTFOLIO P&L</span>
        <span className={`font-mono text-xs ${isUp ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
          {isUp ? '+' : ''}${change.toFixed(2)}
        </span>
      </div>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <XAxis dataKey="time" tick={{ fill: '#6e7681', fontSize: 10, fontFamily: 'monospace' }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
          <YAxis tick={{ fill: '#6e7681', fontSize: 10, fontFamily: 'monospace' }} tickLine={false} axisLine={false} tickFormatter={(v: number) => `$${(v/1000).toFixed(1)}k`} width={44} />
          <Tooltip
            contentStyle={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: 4, fontFamily: 'monospace', fontSize: 11 }}
            labelStyle={{ color: '#8b949e' }}
            itemStyle={{ color: '#209dd7' }}
            formatter={(v: unknown) => [`$${(v as number).toFixed(2)}`, 'Value']}
          />
          <ReferenceLine y={baseline} stroke="#30363d" strokeDasharray="3 3" />
          <Line type="monotone" dataKey="value" stroke="#209dd7" strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: '#209dd7' }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
