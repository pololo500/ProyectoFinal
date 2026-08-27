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
            alerts.add("⚠️ $crisis momento(s) difícil(es) detectado(s) hoy")
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

    private val _nowPlaying = MutableLiveData<String?>(null)
    val nowPlaying: LiveData<String?> = _nowPlaying

    private val _storyPlaying = MutableLiveData(false)
    val storyPlaying: LiveData<Boolean> = _storyPlaying

    private var readingStoryId: String? = null

    private val _songCount = MutableLiveData(-1)
    val songCount: LiveData<Int> = _songCount

    private val _musicMessage = MutableLiveData<String?>()
    val musicMessage: LiveData<String?> = _musicMessage

    fun applyRobotStatus(status: JSONObject) {
        val reading = status.optJSONObject("currently_reading")
        val title = reading?.optString("title").orEmpty()
        val id = reading?.optString("id").orEmpty()
        if (title.isNotBlank() && id.isNotBlank()) {
            readingStoryId = id
            _storyPlaying.value = true
            _nowPlaying.value = title
            return
        }
        readingStoryId = null
        _storyPlaying.value = false
        val playing = if (status.isNull("currently_playing")) null
        else status.optString("currently_playing", null)?.ifBlank { null }
        _nowPlaying.value = playing
    }

    fun refreshMusic() {
        RobotConnectionManager.fetchMusic { result ->
                when (result) {
                    is ApiResult.Success -> {
                    val songs = result.data.optJSONArray("songs")
                    _songCount.value = songs?.length() ?: 0
                    if (_storyPlaying.value == true) {
                        return@fetchMusic
                    }
                    val playing = if (result.data.isNull("currently_playing")) null
                    else result.data.optString("currently_playing", null)?.ifBlank { null }
                    _nowPlaying.value = playing
                }
                is ApiResult.Error -> { /* keep */ }
            }
        }
    }

    fun playNow() {
        val storyId = readingStoryId
        if (!storyId.isNullOrBlank()) {
            RobotConnectionManager.playStory(storyId) { playResult ->
                _musicMessage.value = when (playResult) {
                    is ApiResult.Success -> null
                    is ApiResult.Error -> playResult.message.ifBlank { "¿Está conectado el peluche?" }
                }
            }
            return
        }
        RobotConnectionManager.fetchMusic { result ->
            when (result) {
                is ApiResult.Error -> {
                    _musicMessage.value = result.message.ifBlank { "¿Está conectado el peluche?" }
                }
                is ApiResult.Success -> {
                    val songs = result.data.optJSONArray("songs")
                    val names = mutableListOf<String>()
                    if (songs != null) {
                        for (i in 0 until songs.length()) {
                            val name = songs.optJSONObject(i)?.optString("filename").orEmpty()
                            if (name.isNotBlank()) names.add(name)
                        }
                    }
                    _songCount.value = names.size
                    if (names.isEmpty()) {
                        _musicMessage.value = "Cargá una en Archivos"
                        return@fetchMusic
                    }
                    val last = RobotConnectionManager.lastPlayedSong()
                    val target = last?.takeIf { it in names } ?: names.first()
                    RobotConnectionManager.playMusic(target) { playResult ->
                        _musicMessage.value = when (playResult) {
                            is ApiResult.Success -> null
                            is ApiResult.Error -> playResult.message.ifBlank { "¿Está conectado el peluche?" }
                        }
                        refreshMusic()
                    }
                }
            }
        }
    }

    fun stopNow() {
        RobotConnectionManager.stopStory { }
        RobotConnectionManager.stopMusic { result ->
            readingStoryId = null
            _storyPlaying.value = false
            _musicMessage.value = when (result) {
                is ApiResult.Success -> null
                is ApiResult.Error -> result.message.ifBlank { "¿Está conectado el peluche?" }
            }
            refreshMusic()
        }
    }
}
