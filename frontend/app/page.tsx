'use client'
import { useState, useEffect, useCallback } from 'react'
import type { Portfolio, WatchlistItem, Snapshot } from '@/types'
import { useMarketData } from '@/hooks/useMarketData'
import Header from '@/components/Header'
import Watchlist from '@/components/Watchlist'
import MainChart from '@/components/MainChart'
import PositionsTable from '@/components/PositionsTable'
import TradeBar from '@/components/TradeBar'
import PortfolioHeatmap from '@/components/PortfolioHeatmap'
import PnLChart from '@/components/PnLChart'
import ChatPanel from '@/components/ChatPanel'

export default function Home() {
  const { prices, priceHistory, status } = useMarketData()
  const [portfolio, setPortfolio] = useState<Portfolio>({ cash_balance: 0, total_value: 0, positions: [] })
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)

  const fetchPortfolio = useCallback(async () => {
    try {
      const res = await fetch('/api/portfolio')
      if (res.ok) setPortfolio(await res.json())
    } catch { /* ignore */ }
  }, [])

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await fetch('/api/watchlist')
      if (res.ok) setWatchlist(await res.json())
    } catch { /* ignore */ }
  }, [])

  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch('/api/portfolio/history')
      if (res.ok) setSnapshots(await res.json())
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    fetchPortfolio()
    fetchWatchlist()
    fetchHistory()
    const portfolioInterval = setInterval(fetchPortfolio, 5000)
    const historyInterval = setInterval(fetchHistory, 10000)
    return () => { clearInterval(portfolioInterval); clearInterval(historyInterval) }
  }, [fetchPortfolio, fetchWatchlist, fetchHistory])

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#0d1117] text-[#e6edf3]">
      <Header totalValue={portfolio.total_value} cashBalance={portfolio.cash_balance} status={status} />

      <div className="flex flex-1 overflow-hidden">
        {/* Left: Watchlist ~260px */}
        <div className="w-64 flex-shrink-0 overflow-hidden">
          <Watchlist
            prices={prices}
            priceHistory={priceHistory}
            watchlist={watchlist}
            selectedTicker={selectedTicker}
            onSelectTicker={setSelectedTicker}
            onWatchlistChanged={fetchWatchlist}
          />
        </div>

        {/* Center: Charts + table + trade bar */}
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">
          {/* Main chart */}
          <div className="flex-1 min-h-0 border-b border-[#30363d]" style={{ maxHeight: '45%' }}>
            <MainChart ticker={selectedTicker} priceHistory={priceHistory} prices={prices} />
          </div>

          {/* Heatmap + P&L row */}
          <div className="flex border-b border-[#30363d]" style={{ height: '120px' }}>
            <div className="flex-1 border-r border-[#30363d] overflow-hidden">
              <div className="px-3 py-1 border-b border-[#21262d]">
                <span className="text-[#ecad0a] font-mono text-xs font-bold tracking-widest">HOLDINGS</span>
              </div>
              <div className="h-[calc(100%-24px)]">
                <PortfolioHeatmap positions={portfolio.positions} cashBalance={portfolio.cash_balance} totalValue={portfolio.total_value} />
              </div>
            </div>
            <div className="w-64 flex-shrink-0 overflow-hidden">
              <PnLChart snapshots={snapshots} />
            </div>
          </div>

          {/* Positions table */}
          <div className="border-b border-[#30363d] overflow-y-auto" style={{ maxHeight: '160px' }}>
            <div className="px-3 py-1 border-b border-[#21262d] sticky top-0 bg-[#161b22]">
              <span className="text-[#ecad0a] font-mono text-xs font-bold tracking-widest">POSITIONS</span>
            </div>
            <PositionsTable positions={portfolio.positions} />
          </div>

          {/* Trade bar */}
          <TradeBar selectedTicker={selectedTicker} onTradeExecuted={() => { fetchPortfolio(); fetchHistory() }} />
        </div>

        {/* Right: Chat ~300px */}
        <div className="w-72 flex-shrink-0 overflow-hidden">
          <ChatPanel onTradeExecuted={() => { fetchPortfolio(); fetchHistory() }} onWatchlistChanged={fetchWatchlist} />
        </div>
      </div>
    </div>
  )
}
