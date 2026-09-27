<script setup lang="ts">
/**
 * Heatmap - D3 heatmap for dispersion visualization
 */
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as d3 from 'd3'
import { currentLocale } from '@/i18n/locale'
import { formatNumber } from '@/i18n/format'
import { t } from '@/i18n'

interface DataItem {
  x: number
  value: number
}

interface Props {
  data: DataItem[]
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  height: 120
})

const containerRef = ref<HTMLDivElement | null>(null)
let resizeObserver: ResizeObserver | null = null

function render() {
  if (!containerRef.value || !props.data.length) return

  const container = containerRef.value
  container.innerHTML = ''

  const margin = { top: 10, right: 20, bottom: 30, left: 50 }
  const width = container.clientWidth - margin.left - margin.right
  const height = props.height - margin.top - margin.bottom

  if (width <= 0 || height <= 0) return

  const svg = d3.select(container)
    .append('svg')
    .attr('width', width + margin.left + margin.right)
    .attr('height', height + margin.top + margin.bottom)
    .append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  const maxValue = d3.max(props.data, (d: DataItem) => d.value) || 1

  // Color scale
  const colorScale = d3.scaleSequential(d3.interpolateBlues)
    .domain([0, maxValue])

  const cellCount = props.data.length
  const x = d3.scaleLinear()
    .domain([0, cellCount])
    .range([0, width])

  const tickStep = Math.max(1, Math.ceil(cellCount / 10))
  const tickValues = Array.from(
    { length: Math.floor(cellCount / tickStep) + 1 },
    (_, index) => index * tickStep,
  ).filter((value) => value <= cellCount)
  if (tickValues[tickValues.length - 1] !== cellCount) tickValues.push(cellCount)

  svg.append('g')
    .attr('transform', `translate(0,${height})`)
    .call(d3.axisBottom(x).tickValues(tickValues).tickFormat((d) => `${Math.round(Number(d) / cellCount * 100)}%`))

  // Bars/cells
  svg.selectAll<SVGRectElement, DataItem>('.cell')
    .data(props.data)
    .enter()
    .append('rect')
    .attr('class', 'cell')
    .attr('x', (_d: DataItem, index: number) => x(index))
    .attr('y', 0)
    .attr('width', (_d: DataItem, index: number) => Math.max(1, x(index + 1) - x(index) - 1))
    .attr('height', height)
    .attr('fill', (d: DataItem) => colorScale(d.value))
    .attr('rx', 1)
    .on('mouseover', function(_event: MouseEvent, d: DataItem) {
      d3.select(this).attr('stroke', 'var(--color-neutral-900)').attr('stroke-width', 1)

      // Show tooltip
      svg.append('text')
        .attr('class', 'tooltip')
        .attr('x', (_event.currentTarget as SVGRectElement).x.baseVal.value + Math.max(1, (_event.currentTarget as SVGRectElement).width.baseVal.value) / 2)
        .attr('y', -5)
        .attr('text-anchor', 'middle')
        .text(formatNumber(d.value))
    })
    .on('mouseout', function() {
      d3.select(this).attr('stroke', null)
      svg.selectAll('.tooltip').remove()
    })

  // Y axis label
  svg.append('text')
    .attr('transform', 'rotate(-90)')
    .attr('x', -height / 2)
    .attr('y', -35)
    .attr('text-anchor', 'middle')
    .attr('class', 'axis-label')
    .text(t('analysis.charts.frequency'))
}

onMounted(() => {
  nextTick(render)

  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      render()
    })
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
})

watch(() => props.data, render, { deep: true })
// Axis and label numbers follow the interface language.
watch(() => currentLocale(), render)
</script>

<template>
  <div ref="containerRef" class="heatmap" />
</template>

<style scoped>
@reference "../../../style.css";

.heatmap {
  @apply w-full;
}

.heatmap :deep(text) {
  @apply fill-neutral-600 dark:fill-neutral-400;
  font-size: 11px;
}

.heatmap :deep(.tooltip) {
  @apply fill-neutral-900 dark:fill-neutral-100;
  font-size: 11px;
  font-weight: 600;
}

.heatmap :deep(.axis-label) {
  @apply fill-neutral-500 dark:fill-neutral-500;
  font-size: 10px;
}

.heatmap :deep(.domain),
.heatmap :deep(.tick line) {
  @apply stroke-neutral-300 dark:stroke-neutral-600;
}
</style>
