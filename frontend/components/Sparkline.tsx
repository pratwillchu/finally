interface SparklineProps {
  data: number[]
  width?: number
  height?: number
}

export default function Sparkline({ data, width = 64, height = 24 }: SparklineProps) {
  if (data.length < 2) {
    return <div style={{ width, height }} className="bg-[#21262d] rounded" />
  }

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1

  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width
    const y = height - ((v - min) / range) * height
    return `${x},${y}`
  }).join(' ')

  const isUp = data[data.length - 1] >= data[0]
  const color = isUp ? '#3fb950' : '#f85149'

  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        points={points}
      />
    </svg>
  )
}
