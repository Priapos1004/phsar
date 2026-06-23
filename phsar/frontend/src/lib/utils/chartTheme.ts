import type { EChartsOption } from 'echarts';
import { scoreColor } from '$lib/utils/chartColors';
import { formatDecimalDigits } from '$lib/utils/formatString';

/** Shared score gauge (0–10, color-ramped by value). Used by the anime-page
 * RatingsOverviewStats and the /ratings statistics Overview so the two can't
 * drift in shape. */
export function scoreGaugeOption(value: number): EChartsOption {
	const color = scoreColor(value);
	return {
		series: [
			{
				type: 'gauge',
				emphasis: { disabled: true },
				startAngle: 220,
				endAngle: -40,
				min: 0,
				max: 10,
				radius: '100%',
				center: ['50%', '55%'],
				pointer: { show: false },
				progress: { show: true, width: 10, roundCap: true, itemStyle: { color } },
				axisLine: { lineStyle: { width: 10, color: [[1, 'rgba(0,0,0,0.08)']] } },
				axisTick: { show: false },
				splitLine: { show: false },
				axisLabel: { show: false },
				detail: {
					offsetCenter: [0, '0%'],
					fontSize: 22,
					fontWeight: 'bold',
					color,
					formatter: (val: number) => formatDecimalDigits(val, 2),
				},
				data: [{ value }],
			},
		],
	};
}
