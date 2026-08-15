package com.example.aplicacionparacelular.ui.metrics

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import com.example.aplicacionparacelular.network.ApiResult
import com.example.aplicacionparacelular.network.RobotConnectionManager
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

class MetricsViewModel : ViewModel() {

    /** Pillar-based interaction counts for the selected period. */
    data class PillarData(
        val emocional: Int = 0,
        val cognitivo: Int = 0,
        val vincular: Int = 0,
        val autonomia: Int = 0,
        val general: Int = 0
    )

    data class DailySummary(
        val date: String,
        val interactions: Int,
        val durationMinutes: Int,
        val crisisCount: Int,
        val newWords: Int,
        val gamesPlayed: Int,
        val routinesCompleted: Int
    )

    private val _pillars = MutableLiveData(PillarData())
    val pillars: LiveData<PillarData> = _pillars

    private val _todaySummary = MutableLiveData<DailySummary?>()
    val todaySummary: LiveData<DailySummary?> = _todaySummary

    private val _weekSummaries = MutableLiveData<List<DailySummary>>(emptyList())
    val weekSummaries: LiveData<List<DailySummary>> = _weekSummaries

    private val _vocabularyTotal = MutableLiveData(0)
    val vocabularyTotal: LiveData<Int> = _vocabularyTotal

    private val _newWordsWeek = MutableLiveData(0)
    val newWordsWeek: LiveData<Int> = _newWordsWeek

    private val _isLoading = MutableLiveData(false)
    val isLoading: LiveData<Boolean> = _isLoading

    fun loadTodayMetrics() {
        _isLoading.value = true
        RobotConnectionManager.fetchTelemetryToday { result ->
            _isLoading.value = false
            when (result) {
                is ApiResult.Success -> parseDailySummary(result.data, isToday = true)
                is ApiResult.Error -> { /* Keep current values */ }
            }
        }
    }

    fun loadWeekMetrics() {
        _isLoading.value = true
        val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        val calendar = Calendar.getInstance()
        val summaries = mutableListOf<DailySummary>()
        var pendingRequests = 7
        var totalNewWords = 0

        for (i in 6 downTo 0) {
            calendar.timeInMillis = System.currentTimeMillis()
            calendar.add(Calendar.DAY_OF_YEAR, -i)
            val dateStr = dateFormat.format(calendar.time)

            RobotConnectionManager.fetchTelemetry(dateStr) { result ->
                pendingRequests--
                when (result) {
                    is ApiResult.Success -> {
                        val summary = extractDailySummary(result.data, dateStr)
                        summaries.add(summary)
                        totalNewWords += summary.newWords
                    }
                    is ApiResult.Error -> {
                        summaries.add(DailySummary(dateStr, 0, 0, 0, 0, 0, 0))
                    }
                }
                if (pendingRequests <= 0) {
                    _weekSummaries.value = summaries.sortedBy { it.date }
                    _newWordsWeek.value = totalNewWords
                    _isLoading.value = false
                }
            }
        }
    }

    private fun parseDailySummary(data: JSONObject, isToday: Boolean) {
        val summary = data.optJSONObject("summary") ?: return
        val dateStr = data.optString("date", "")

        val ds = DailySummary(
            date = dateStr,
            interactions = summary.optInt("total_interactions", 0),
            durationMinutes = (summary.optDouble("total_duration_s", 0.0) / 60).toInt(),
            crisisCount = summary.optInt("crisis_count", 0),
            newWords = summary.optInt("new_words_today", 0),
            gamesPlayed = summary.optInt("games_played", 0),
            routinesCompleted = summary.optInt("routines_completed", 0)
        )

        if (isToday) {
            _todaySummary.value = ds
        }

        // Parse pillar counts
        val pillarCounts = summary.optJSONObject("pillar_counts")
        if (pillarCounts != null) {
            _pillars.value = PillarData(
                emocional = pillarCounts.optInt("emocional", 0),
                cognitivo = pillarCounts.optInt("cognitivo", 0),
                vincular = pillarCounts.optInt("vincular", 0),
                autonomia = pillarCounts.optInt("autonomia", 0),
                general = pillarCounts.optInt("general", 0)
            )
        }

        // Look for vocabulary total in events
        val events = data.optJSONArray("events")
        if (events != null) {
            for (i in events.length() - 1 downTo 0) {
                val event = events.optJSONObject(i) ?: continue
                if (event.optString("type") == "vocabulary") {
                    val total = event.optInt("total_known_words", 0)
                    if (total > 0) {
                        _vocabularyTotal.value = total
                        break
                    }
                }
            }
        }
    }

    private fun extractDailySummary(data: JSONObject, dateStr: String): DailySummary {
        val summary = data.optJSONObject("summary")
        return if (summary != null) {
            DailySummary(
                date = dateStr,
                interactions = summary.optInt("total_interactions", 0),
                durationMinutes = (summary.optDouble("total_duration_s", 0.0) / 60).toInt(),
                crisisCount = summary.optInt("crisis_count", 0),
                newWords = summary.optInt("new_words_today", 0),
                gamesPlayed = summary.optInt("games_played", 0),
                routinesCompleted = summary.optInt("routines_completed", 0)
            )
        } else {
            DailySummary(dateStr, 0, 0, 0, 0, 0, 0)
        }
    }
}
