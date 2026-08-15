package com.example.aplicacionparacelular.ui.metrics

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.os.Bundle
import android.util.AttributeSet
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import com.example.aplicacionparacelular.R
import com.example.aplicacionparacelular.databinding.FragmentMetricsBinding

class MetricsFragment : Fragment() {

    private var _binding: FragmentMetricsBinding? = null
    private val binding get() = _binding!!
    private lateinit var viewModel: MetricsViewModel

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        viewModel = ViewModelProvider(this).get(MetricsViewModel::class.java)
        _binding = FragmentMetricsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Period selector buttons
        binding.btnToday.setOnClickListener {
            viewModel.loadTodayMetrics()
            highlightPeriodButton(0)
        }
        binding.btnWeek.setOnClickListener {
            viewModel.loadWeekMetrics()
            highlightPeriodButton(1)
        }
        binding.btnMonth.setOnClickListener {
            viewModel.loadWeekMetrics() // Same data for now
            highlightPeriodButton(2)
        }

        // Observe today's summary
        viewModel.todaySummary.observe(viewLifecycleOwner) { summary ->
            if (summary != null) {
                binding.txtTotalInteractions.text = summary.interactions.toString()
                binding.txtTotalPlaytime.text = "${summary.durationMinutes} min"
                binding.txtGamesPlayed.text = summary.gamesPlayed.toString()
                binding.txtRoutinesCompleted.text = summary.routinesCompleted.toString()
                binding.txtCrisisCount.text = summary.crisisCount.toString()
            }
        }

        // Observe pillar data
        viewModel.pillars.observe(viewLifecycleOwner) { pillars ->
            binding.pillarChart.setData(
                listOf(
                    pillars.emocional,
                    pillars.cognitivo,
                    pillars.vincular,
                    pillars.autonomia
                ),
                listOf("Emocional", "Cognitivo", "Vincular", "Autonomía"),
                listOf(
                    ContextCompat.getColor(requireContext(), R.color.card_emotion_alert),
                    ContextCompat.getColor(requireContext(), R.color.tertiary),
                    ContextCompat.getColor(requireContext(), R.color.primary_light),
                    ContextCompat.getColor(requireContext(), R.color.card_emotion_happy)
                )
            )
        }

        // Observe vocabulary
        viewModel.vocabularyTotal.observe(viewLifecycleOwner) { total ->
            binding.txtVocabTotal.text = "$total palabras conocidas"
        }
        viewModel.newWordsWeek.observe(viewLifecycleOwner) { newWords ->
            binding.txtVocabNew.text = "$newWords esta semana"
        }

        // Observe weekly bar chart data
        viewModel.weekSummaries.observe(viewLifecycleOwner) { summaries ->
            val values = summaries.map { it.interactions }
            val labels = summaries.map { it.date.takeLast(5) } // MM-DD
            binding.weekChart.setBarData(values, labels,
                ContextCompat.getColor(requireContext(), R.color.primary)
            )
        }

        // Load initial data
        viewModel.loadTodayMetrics()
        highlightPeriodButton(0)
    }

    private fun highlightPeriodButton(index: Int) {
        val buttons = listOf(binding.btnToday, binding.btnWeek, binding.btnMonth)
        buttons.forEachIndexed { i, btn ->
            if (i == index) {
                btn.setBackgroundColor(ContextCompat.getColor(requireContext(), R.color.primary))
                btn.setTextColor(ContextCompat.getColor(requireContext(), R.color.white))
            } else {
                btn.setBackgroundColor(ContextCompat.getColor(requireContext(), R.color.card_bg_lavender))
                btn.setTextColor(ContextCompat.getColor(requireContext(), R.color.primary))
            }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

/**
 * Custom View: gráfico de donut simple para mostrar distribución por pilar.
 */
class PillarDonutChart @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 32f
        strokeCap = Paint.Cap.ROUND
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER
        color = 0xFF1C1B1F.toInt()
    }
    private val rect = RectF()
    private var values: List<Int> = emptyList()
    private var labels: List<String> = emptyList()
    private var colors: List<Int> = emptyList()

    fun setData(values: List<Int>, labels: List<String>, colors: List<Int>) {
        this.values = values
        this.labels = labels
        this.colors = colors
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val total = values.sum().toFloat()
        if (total == 0f) {
            textPaint.textSize = 28f
            canvas.drawText("Sin datos", width / 2f, height / 2f, textPaint)
            return
        }

        val padding = 40f
        val size = minOf(width, height).toFloat() - padding * 2
        rect.set(
            (width - size) / 2f,
            (height - size) / 2f,
            (width + size) / 2f,
            (height + size) / 2f
        )

        var startAngle = -90f
        for (i in values.indices) {
            if (values[i] <= 0) continue
            val sweep = (values[i] / total) * 360f
            paint.color = if (i < colors.size) colors[i] else 0xFF999999.toInt()
            canvas.drawArc(rect, startAngle, sweep - 2f, false, paint)
            startAngle += sweep
        }

        // Center text showing total
        textPaint.textSize = 36f
        canvas.drawText(total.toInt().toString(), width / 2f, height / 2f - 8f, textPaint)
        textPaint.textSize = 20f
        canvas.drawText("total", width / 2f, height / 2f + 24f, textPaint)
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val size = minOf(
            MeasureSpec.getSize(widthMeasureSpec),
            MeasureSpec.getSize(heightMeasureSpec)
        )
        val finalSize = if (size > 0) size else 300
        setMeasuredDimension(finalSize, finalSize)
    }
}

/**
 * Custom View: gráfico de barras simple para mostrar interacciones semanales.
 */
class WeekBarChart @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val barPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER
        textSize = 24f
        color = 0xFF9E9E9E.toInt()
    }
    private val valuePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER
        textSize = 22f
        color = 0xFF1C1B1F.toInt()
    }
    private var values: List<Int> = emptyList()
    private var labels: List<String> = emptyList()
    private var barColor: Int = 0xFF6750A4.toInt()

    fun setBarData(values: List<Int>, labels: List<String>, color: Int) {
        this.values = values
        this.labels = labels
        this.barColor = color
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (values.isEmpty()) {
            textPaint.textSize = 28f
            canvas.drawText("Sin datos", width / 2f, height / 2f, textPaint)
            return
        }

        val maxVal = (values.maxOrNull() ?: 1).coerceAtLeast(1)
        val barCount = values.size
        val spacing = 16f
        val labelHeight = 36f
        val topPadding = 28f
        val barWidth = (width.toFloat() - spacing * (barCount + 1)) / barCount
        val chartHeight = height.toFloat() - labelHeight - topPadding

        barPaint.color = barColor

        for (i in values.indices) {
            val barHeight = (values[i].toFloat() / maxVal) * (chartHeight - 30f)
            val left = spacing + i * (barWidth + spacing)
            val top = topPadding + chartHeight - barHeight
            val right = left + barWidth
            val bottom = topPadding + chartHeight

            // Draw bar with rounded top
            barPaint.color = barColor
            canvas.drawRoundRect(left, top, right, bottom, 8f, 8f, barPaint)

            // Draw value above bar
            if (values[i] > 0) {
                canvas.drawText(values[i].toString(), left + barWidth / 2, top - 6f, valuePaint)
            }

            // Draw label below
            if (i < labels.size) {
                textPaint.textSize = 20f
                canvas.drawText(
                    labels[i],
                    left + barWidth / 2,
                    height.toFloat() - 4f,
                    textPaint
                )
            }
        }
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val w = MeasureSpec.getSize(widthMeasureSpec)
        val h = MeasureSpec.getSize(heightMeasureSpec)
        setMeasuredDimension(w, if (h > 0) h else 300)
    }
}
