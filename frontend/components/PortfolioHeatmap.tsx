'use client'
import type { Position } from '@/types'

interface PortfolioHeatmapProps {
  positions: Position[]
  cashBalance: number
  totalValue: number
}

function pnlColor(pct: number): string {
  if (pct > 5) return '#2ea043'
  if (pct > 0) return '#3fb950'
  if (pct === 0) return '#30363d'
  if (pct > -5) return '#da3633'
  return '#b91c1c'
}

export default function PortfolioHeatmap({ positions, cashBalance, totalValue }: PortfolioHeatmapProps) {
  if (positions.length === 0 && cashBalance <= 0) {
    return <div className="flex items-center justify-center h-full text-[#6e7681] font-mono text-xs">NO POSITIONS</div>
  }

  const cashWeight = cashBalance / totalValue

  const items = positions.map(p => ({
    ticker: p.ticker,
    value: p.quantity * p.current_price,
    weight: (p.quantity * p.current_price) / totalValue,
    pnlPct: p.pnl_pct,
  })).sort((a, b) => b.weight - a.weight)

  return (
    <div className="flex flex-wrap gap-1 p-2 h-full content-start">
      {items.map(item => (
        <div
          key={item.ticker}
          className="flex flex-col items-center justify-center rounded text-center overflow-hidden"
          style={{
            backgroundColor: pnlColor(item.pnlPct),
            width: `${Math.max(item.weight * 100 * 0.95, 4)}%`,
            minWidth: '48px',
            height: '56px',
            flexShrink: 0,
          }}
        >
          <div className="text-white font-mono font-bold text-xs">{item.ticker}</div>
          <div className="text-white font-mono text-xs opacity-80">{item.pnlPct >= 0 ? '+' : ''}{item.pnlPct.toFixed(1)}%</div>
        </div>
      ))}
      <div
        className="flex flex-col items-center justify-center rounded text-center"
        style={{
          backgroundColor: '#21262d',
          width: `${Math.max(cashWeight * 100 * 0.95, 4)}%`,
          minWidth: '48px',
          height: '56px',
          flexShrink: 0,
        }}
      >
        <div className="text-[#8b949e] font-mono text-xs">CASH</div>
        <div className="text-[#6e7681] font-mono text-xs">{(cashWeight * 100).toFixed(0)}%</div>
      </div>
    </div>
  )
}
