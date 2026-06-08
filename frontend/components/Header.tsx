'use client'
import type { ConnectionStatus } from '@/hooks/useMarketData'

interface HeaderProps {
  totalValue: number
  cashBalance: number
  status: ConnectionStatus
}

export default function Header({ totalValue, cashBalance, status }: HeaderProps) {
  const statusColor = status === 'connected' ? '#3fb950' : status === 'connecting' ? '#ecad0a' : '#f85149'
  const statusLabel = status === 'connected' ? 'LIVE' : status === 'connecting' ? 'CONNECTING' : 'DISCONNECTED'

  return (
    <header className="flex items-center justify-between px-4 py-2 border-b border-[#30363d] bg-[#161b22]">
      <div className="flex items-center gap-3">
        <span className="text-[#ecad0a] font-mono font-bold text-lg tracking-wider">FIN<span className="text-[#209dd7]">ALLY</span></span>
        <span className="text-[#6e7681] text-xs">AI Trading Workstation</span>
      </div>
      <div className="flex items-center gap-6">
        <div className="text-center">
          <div className="text-[#8b949e] text-xs">PORTFOLIO VALUE</div>
          <div className="text-[#e6edf3] font-mono font-bold text-xl">${totalValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
        </div>
        <div className="text-center">
          <div className="text-[#8b949e] text-xs">CASH</div>
          <div className="text-[#e6edf3] font-mono text-sm">${cashBalance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: statusColor }}></div>
          <span className="text-xs font-mono" style={{ color: statusColor }}>{statusLabel}</span>
        </div>
      </div>
    </header>
  )
}
