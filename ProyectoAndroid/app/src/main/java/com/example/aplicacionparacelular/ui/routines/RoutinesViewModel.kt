package com.example.aplicacionparacelular.ui.routines

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import com.example.aplicacionparacelular.network.ApiResult
import com.example.aplicacionparacelular.network.RobotConnectionManager
import org.json.JSONArray
import org.json.JSONObject

data class RoutineItem(
    val id: String,
    val name: String,
    val time: String,
    val reminderMessage: String,
    val transitionFrom: String,
    val transitionTo: String,
    val successMessage: String,
    val preReminderMinutes: Int,
    val enabled: Boolean,
    val reminded: Boolean = false,
    val completed: Boolean = false
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("id", id)
            put("name", name)
            put("time", time)
            put("reminder_message", reminderMessage)
            put("transition_from", transitionFrom)
            put("transition_to", transitionTo)
            put("success_message", successMessage)
            put("pre_reminder_minutes", preReminderMinutes)
            put("enabled", enabled)
        }
    }

    companion object {
        fun fromJson(json: JSONObject): RoutineItem {
            return RoutineItem(
                id = json.optString("id", ""),
                name = json.optString("name", ""),
                time = json.optString("time", "00:00"),
                reminderMessage = json.optString("reminder_message", ""),
                transitionFrom = json.optString("transition_from", ""),
                transitionTo = json.optString("transition_to", ""),
                successMessage = json.optString("success_message", ""),
                preReminderMinutes = json.optInt("pre_reminder_minutes", 5),
                enabled = json.optBoolean("enabled", true),
                reminded = json.optBoolean("reminded", false),
                completed = json.optBoolean("completed", false)
            )
        }
    }
}

class RoutinesViewModel : ViewModel() {

    private val _routines = MutableLiveData<List<RoutineItem>>(emptyList())
    val routines: LiveData<List<RoutineItem>> = _routines

    private val _isLoading = MutableLiveData(false)
    val isLoading: LiveData<Boolean> = _isLoading

    private val _syncStatus = MutableLiveData<String?>()
    val syncStatus: LiveData<String?> = _syncStatus

    fun loadRoutines() {
        _isLoading.value = true
        RobotConnectionManager.fetchRoutines { result ->
            _isLoading.value = false
            when (result) {
                is ApiResult.Success -> {
                    val routinesArray = result.data.optJSONArray("routines") ?: JSONArray()
                    val list = mutableListOf<RoutineItem>()
                    for (i in 0 until routinesArray.length()) {
                        val json = routinesArray.optJSONObject(i) ?: continue
                        list.add(RoutineItem.fromJson(json))
                    }
                    _routines.value = list
                }
                is ApiResult.Error -> {
                    _syncStatus.value = "Error: ${result.message}"
                }
            }
        }
    }

    fun addRoutine(routine: RoutineItem) {
        val current = _routines.value?.toMutableList() ?: mutableListOf()
        current.add(routine)
        _routines.value = current
        syncRoutines()
    }

    fun removeRoutine(position: Int) {
        val current = _routines.value?.toMutableList() ?: return
        if (position in current.indices) {
            current.removeAt(position)
            _routines.value = current
            syncRoutines()
        }
    }

    fun toggleRoutine(position: Int) {
        val current = _routines.value?.toMutableList() ?: return
        if (position in current.indices) {
            val routine = current[position]
            current[position] = routine.copy(enabled = !routine.enabled)
            _routines.value = current
            syncRoutines()
        }
    }

    fun updateRoutine(position: Int, routine: RoutineItem) {
        val current = _routines.value?.toMutableList() ?: return
        if (position in current.indices) {
            current[position] = routine
            _routines.value = current
            syncRoutines()
        }
    }

    private fun syncRoutines() {
        val routinesList = _routines.value ?: return
        val jsonArray = JSONArray()
        for (routine in routinesList) {
            jsonArray.put(routine.toJson())
        }
        val body = JSONObject().apply { put("routines", jsonArray) }

        RobotConnectionManager.updateRoutines(body) { result ->
            when (result) {
                is ApiResult.Success -> _syncStatus.value = "✅ Sincronizado"
                is ApiResult.Error -> _syncStatus.value = "⚠ No sincronizado: ${result.message}"
            }
        }
    }
}
