package com.example.aplicacionparacelular.ui.dashboard

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import com.example.aplicacionparacelular.network.ApiResult
import com.example.aplicacionparacelular.network.RobotConnectionManager
import org.json.JSONObject

class DashboardViewModel : ViewModel() {

    private val _totalInteractions = MutableLiveData("0")
    val totalInteractions: LiveData<String> = _totalInteractions

    private val _playtimeMinutes = MutableLiveData("0 min")
    val playtimeMinutes: LiveData<String> = _playtimeMinutes

    private val _moodLabel = MutableLiveData("Sin datos")
    val moodLabel: LiveData<String> = _moodLabel

    private val _crisisCount = MutableLiveData(0)
    val crisisCount: LiveData<Int> = _crisisCount

    private val _newWordsToday = MutableLiveData(0)
    val newWordsToday: LiveData<Int> = _newWordsToday

    private val _alertMessages = MutableLiveData<List<String>>(emptyList())
    val alertMessages: LiveData<List<String>> = _alertMessages

    private val _powerOn = MutableLiveData(true)
    val powerOn: LiveData<Boolean> = _powerOn

    fun refreshTelemetry() {
        RobotConnectionManager.fetchTelemetryToday { result ->
            when (result) {
                is ApiResult.Success -> parseTelemetry(result.data)
                is ApiResult.Error -> { /* Keep current values */ }
            }
        }
    }

    private fun parseTelemetry(data: JSONObject) {
        val summary = data.optJSONObject("summary") ?: return

        val interactions = summary.optInt("total_interactions", 0)
        _totalInteractions.value = interactions.toString()

        val durationSecs = summary.optDouble("total_duration_s", 0.0)
        val minutes = (durationSecs / 60).toInt()
        _playtimeMinutes.value = "$minutes min"

        val crisis = summary.optInt("crisis_count", 0)
        _crisisCount.value = crisis

        val newWords = summary.optInt("new_words_today", 0)
        _newWordsToday.value = newWords

        // Derive mood from recent events
        val events = data.optJSONArray("events")
        var lastEmotion: String? = null
        if (events != null) {
            for (i in events.length() - 1 downTo 0) {
                val event = events.optJSONObject(i) ?: continue
                val emotion = event.optString("emotion", "")
                if (emotion.isNotBlank() && emotion != "null") {
                    lastEmotion = emotion
                    break
                }
            }
        }
        _moodLabel.value = translateEmotion(lastEmotion)

        // Build alert messages
        val alerts = mutableListOf<String>()
        if (crisis > 0) {
            alerts.add("⚠️ $crisis episodio(s) de desregulación emocional detectado(s) hoy")
        }
        if (newWords > 0) {
            alerts.add("📚 $newWords palabra(s) nueva(s) registrada(s) hoy")
        }
        val pillarCounts = summary.optJSONObject("pillar_counts")
        if (pillarCounts != null) {
            val emotional = pillarCounts.optInt("emocional", 0)
            if (emotional > 5) {
                alerts.add("💛 Muchas interacciones emocionales hoy ($emotional)")
            }
        }
        _alertMessages.value = alerts
    }

    private fun translateEmotion(emotion: String?): String {
        return when (emotion?.lowercase()) {
            "happy", "feliz" -> "Feliz 😊"
            "sad", "triste" -> "Triste 😢"
            "angry", "enojado" -> "Enojado 😠"
            "surprised", "sorprendido" -> "Sorprendido 😲"
            "neutral" -> "Tranquilo 😐"
            "calm", "calmo" -> "Tranquilo 😊"
            "fear", "miedo" -> "Asustado 😨"
            null, "" -> "Sin datos"
            else -> emotion ?: "Sin datos"
        }
    }

    fun togglePower() {
        val currentPower = _powerOn.value ?: true
        val newPower = !currentPower
        RobotConnectionManager.setPower(newPower) { result ->
            when (result) {
                is ApiResult.Success -> _powerOn.value = newPower
                is ApiResult.Error -> { /* Revert, keep current state */ }
            }
        }
    }
}
