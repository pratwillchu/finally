'use client'
import { useEffect, useRef } from 'react'
import { createChart, ColorType, LineStyle, LineSeries } from 'lightweight-charts'
import type { UTCTimestamp } from 'lightweight-charts'
import type { PriceHistory, PriceMap } from '@/hooks/useMarketData'

interface MainChartProps {
  ticker: string | null
  priceHistory: PriceHistory
  prices: PriceMap
}

export default function MainChart({ ticker, priceHistory, prices }: MainChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<any>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#0d1117' }, textColor: '#8b949e' },
      grid: { vertLines: { color: '#21262d', style: LineStyle.Dotted }, horzLines: { color: '#21262d', style: LineStyle.Dotted } },
      crosshair: { vertLine: { color: '#30363d' }, horzLine: { color: '#30363d' } },
      rightPriceScale: { borderColor: '#30363d' },
      timeScale: { borderColor: '#30363d', timeVisible: false },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    })
    const series = chart.addSeries(LineSeries, { color: '#209dd7', lineWidth: 2, lastValueVisible: true, priceLineVisible: false })
    chartRef.current = chart
    seriesRef.current = series

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight })
    })
    ro.observe(containerRef.current)

    return () => { ro.disconnect(); chart.remove() }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !ticker) return
    const history = priceHistory[ticker] ?? []
    const data = history.map((price, i) => ({ time: (i + 1) as UTCTimestamp, value: price }))
    seriesRef.current.setData(data)
    if (chartRef.current) chartRef.current.timeScale().fitContent()
  }, [ticker, priceHistory])

  const live = ticker ? prices[ticker] : null
  const changePct = live?.daily_change_pct ?? 0
  const isUp = changePct >= 0

  return (
    <div className="flex flex-col h-full bg-[#0d1117]">
      <div className="flex items-center gap-3 px-3 py-2 border-b border-[#30363d] bg-[#161b22]">
        {ticker ? (
          <>
            <span className="font-mono font-bold text-[#ecad0a]">{ticker}</span>
            {live && (
              <>
                <span className="font-mono text-[#e6edf3] text-lg">${live.price.toFixed(2)}</span>
                <span className={`font-mono text-sm ${isUp ? 'text-[#3fb950]' : 'text-[#f85149]'}`}>
                  {isUp ? '+' : ''}{changePct.toFixed(2)}%
                </span>
              </>
            )}
          </>
        ) : (
          <span className="text-[#6e7681] font-mono text-xs">SELECT A TICKER TO VIEW CHART</span>
        )}
      </div>
      <div ref={containerRef} className="flex-1" />
    </div>
  )
}
