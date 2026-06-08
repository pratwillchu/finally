import type { Position } from '@/types'

interface PositionsTableProps {
  positions: Position[]
}

export default function PositionsTable({ positions }: PositionsTableProps) {
  if (positions.length === 0) {
    return (
      <div className="px-3 py-4 text-[#6e7681] font-mono text-xs text-center">
        NO OPEN POSITIONS
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full font-mono text-xs">
        <thead>
          <tr className="text-[#6e7681] border-b border-[#30363d]">
            <th className="text-left px-3 py-1">TICKER</th>
            <th className="text-right px-2 py-1">QTY</th>
            <th className="text-right px-2 py-1">AVG COST</th>
            <th className="text-right px-2 py-1">CURRENT</th>
            <th className="text-right px-2 py-1">P&L</th>
            <th className="text-right px-3 py-1">%</th>
          </tr>
        </thead>
        <tbody>
          {positions.map(p => {
            const isUp = p.unrealized_pnl >= 0
            const color = isUp ? 'text-[#3fb950]' : 'text-[#f85149]'
            return (
              <tr key={p.ticker} className="border-b border-[#21262d] hover:bg-[#21262d] transition-colors">
                <td className="px-3 py-1.5 text-[#ecad0a] font-bold">{p.ticker}</td>
                <td className="px-2 py-1.5 text-right text-[#e6edf3]">{p.quantity}</td>
                <td className="px-2 py-1.5 text-right text-[#8b949e]">${p.avg_cost.toFixed(2)}</td>
                <td className="px-2 py-1.5 text-right text-[#e6edf3]">${p.current_price.toFixed(2)}</td>
                <td className={`px-2 py-1.5 text-right ${color}`}>${p.unrealized_pnl >= 0 ? '+' : ''}{p.unrealized_pnl.toFixed(2)}</td>
                <td className={`px-3 py-1.5 text-right ${color}`}>{p.pnl_pct >= 0 ? '+' : ''}{p.pnl_pct.toFixed(2)}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
