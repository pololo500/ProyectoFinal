package com.example.aplicacionparacelular.ui.config

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import com.example.aplicacionparacelular.network.ApiResult
import com.example.aplicacionparacelular.network.RobotConnectionManager
import org.json.JSONObject

data class SongItem(
    val filename: String,
    val sizeBytes: Long,
    val modified: String
)

class ConfigViewModel : ViewModel() {

    private val _volumeLimit = MutableLiveData(100)
    val volumeLimit: LiveData<Int> = _volumeLimit

    private val _brightness = MutableLiveData(100)
    val brightness: LiveData<Int> = _brightness

    private val _nightMode = MutableLiveData(false)
    val nightMode: LiveData<Boolean> = _nightMode

    private val _songs = MutableLiveData<List<SongItem>>(emptyList())
    val songs: LiveData<List<SongItem>> = _songs

    private val _statusMessage = MutableLiveData<String?>()
    val statusMessage: LiveData<String?> = _statusMessage

    /**
     * Loads the current robot config from the status endpoint.
     */
    fun loadFromRobot() {
        RobotConnectionManager.executeAsync({ com.example.aplicacionparacelular.network.RobotApiClient.getStatus() }) { result ->
            when (result) {
                is ApiResult.Success -> {
                    _volumeLimit.value = result.data.optInt("volume_limit", 100)
                    _brightness.value = (result.data.optDouble("brightness", 1.0) * 100).toInt()
                    _nightMode.value = result.data.optBoolean("night_mode", false)
                }
                is ApiResult.Error -> { /* Keep defaults */ }
            }
        }
    }

    fun setVolumeLimit(value: Int) {
        _volumeLimit.value = value
    }

    fun setBrightness(value: Int) {
        _brightness.value = value
    }

    /**
     * Sends current volume and brightness to the robot.
     */
    fun applyConfig() {
        val vol = _volumeLimit.value ?: 100
        val bright = (_brightness.value ?: 100) / 100f
        RobotConnectionManager.updateConfig(vol, bright) { result ->
            _statusMessage.value = when (result) {
                is ApiResult.Success -> "✅ Configuración aplicada"
                is ApiResult.Error -> "⚠ Error: ${result.message}"
            }
        }
    }

    fun toggleNightMode() {
        val newValue = !(_nightMode.value ?: false)
        RobotConnectionManager.setNightMode(newValue) { result ->
            when (result) {
                is ApiResult.Success -> {
                    _nightMode.value = newValue
                    _statusMessage.value = if (newValue) "🌙 Modo noche activado" else "☀ Modo noche desactivado"
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "⚠ Error: ${result.message}"
                }
            }
        }
    }

    fun loadSongs() {
        RobotConnectionManager.fetchMusic { result ->
            when (result) {
                is ApiResult.Success -> {
                    val songsArray = result.data.optJSONArray("songs")
                    val list = mutableListOf<SongItem>()
                    if (songsArray != null) {
                        for (i in 0 until songsArray.length()) {
                            val obj = songsArray.optJSONObject(i) ?: continue
                            list.add(SongItem(
                                filename = obj.optString("filename", ""),
                                sizeBytes = obj.optLong("size_bytes", 0),
                                modified = obj.optString("modified", "")
                            ))
                        }
                    }
                    _songs.value = list
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error al cargar canciones: ${result.message}"
                }
            }
        }
    }

    fun deleteSong(filename: String) {
        RobotConnectionManager.deleteMusic(filename) { result ->
            when (result) {
                is ApiResult.Success -> {
                    _statusMessage.value = "Canción eliminada"
                    loadSongs() // Refresh
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error: ${result.message}"
                }
            }
        }
    }

    fun uploadSong(filename: String, data: ByteArray) {
        _statusMessage.value = "Subiendo canción..."
        RobotConnectionManager.uploadMusic(filename, data) { result ->
            when (result) {
                is ApiResult.Success -> {
                    _statusMessage.value = "✅ Canción subida correctamente"
                    loadSongs() // Refresh
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error: ${result.message}"
                }
            }
        }
    }
}
