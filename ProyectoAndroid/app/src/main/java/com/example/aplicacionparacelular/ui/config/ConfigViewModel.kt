package com.example.aplicacionparacelular.ui.config

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import com.example.aplicacionparacelular.network.ApiResult
import com.example.aplicacionparacelular.network.RobotConnectionManager

class ConfigViewModel : ViewModel() {

    private val _volumeLimit = MutableLiveData(100)
    val volumeLimit: LiveData<Int> = _volumeLimit

    private val _brightness = MutableLiveData(100)
    val brightness: LiveData<Int> = _brightness

    private val _nightMode = MutableLiveData(false)
    val nightMode: LiveData<Boolean> = _nightMode

    private val _statusMessage = MutableLiveData<String?>()
    val statusMessage: LiveData<String?> = _statusMessage

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
}
