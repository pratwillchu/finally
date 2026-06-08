'use client'
import { useState, useEffect, useRef } from 'react'
import type { PriceUpdate } from '@/types'

export type PriceMap = Record<string, PriceUpdate>
export type PriceHistory = Record<string, number[]>
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected'

export function useMarketData() {
  const [prices, setPrices] = useState<PriceMap>({})
  const [priceHistory, setPriceHistory] = useState<PriceHistory>({})
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    function connect() {
      setStatus('connecting')
      const es = new EventSource('/api/stream/prices')
      esRef.current = es

      es.onopen = () => setStatus('connected')

      es.onmessage = (event) => {
        try {
          const data: PriceMap = JSON.parse(event.data)
          setPrices(data)
          setPriceHistory(prev => {
            const next = { ...prev }
            for (const [ticker, update] of Object.entries(data)) {
              const history = next[ticker] ?? []
              next[ticker] = [...history.slice(-200), update.price]
            }
            return next
          })
          setStatus('connected')
        } catch {
          // ignore parse errors
        }
      }

      es.onerror = () => {
        setStatus('disconnected')
        es.close()
        setTimeout(connect, 3000)
      }
    }

    connect()
    return () => { esRef.current?.close() }
  }, [])

  return { prices, priceHistory, status }
}
