package com.example.aplicacionparacelular.ui.medical

import android.content.Context
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import org.json.JSONArray
import org.json.JSONObject

data class Appointment(
    val id: String,
    val title: String,
    val date: String,
    val notes: String = ""
)

data class Vaccine(
    val id: String,
    val name: String,
    val scheduledAge: String,
    val applied: Boolean,
    val appliedDate: String = ""
)

class MedicalViewModel : ViewModel() {

    private val _appointments = MutableLiveData<List<Appointment>>(emptyList())
    val appointments: LiveData<List<Appointment>> = _appointments

    private val _vaccines = MutableLiveData<List<Vaccine>>(emptyList())
    val vaccines: LiveData<List<Vaccine>> = _vaccines

    /**
     * Loads appointments and vaccines from local SharedPreferences.
     * Medical data is stored locally only (no communication with Pi needed).
     */
    fun loadData(context: Context) {
        val prefs = context.getSharedPreferences("medical_data", Context.MODE_PRIVATE)

        // Load appointments
        val appointmentsJson = prefs.getString("appointments", null)
        if (appointmentsJson != null) {
            try {
                val arr = JSONArray(appointmentsJson)
                val list = mutableListOf<Appointment>()
                for (i in 0 until arr.length()) {
                    val obj = arr.getJSONObject(i)
                    list.add(Appointment(
                        id = obj.optString("id"),
                        title = obj.optString("title"),
                        date = obj.optString("date"),
                        notes = obj.optString("notes", "")
                    ))
                }
                _appointments.value = list
            } catch (_: Exception) {}
        } else {
            // Default sample data
            _appointments.value = listOf(
                Appointment("1", "Control pediátrico", "15 de septiembre, 10:00"),
                Appointment("2", "Fonoaudióloga", "22 de septiembre, 16:30")
            )
        }

        // Load vaccines
        val vaccinesJson = prefs.getString("vaccines", null)
        if (vaccinesJson != null) {
            try {
                val arr = JSONArray(vaccinesJson)
                val list = mutableListOf<Vaccine>()
                for (i in 0 until arr.length()) {
                    val obj = arr.getJSONObject(i)
                    list.add(Vaccine(
                        id = obj.optString("id"),
                        name = obj.optString("name"),
                        scheduledAge = obj.optString("scheduled_age"),
                        applied = obj.optBoolean("applied", false),
                        appliedDate = obj.optString("applied_date", "")
                    ))
                }
                _vaccines.value = list
            } catch (_: Exception) {}
        } else {
            // Default Argentine vaccination calendar
            _vaccines.value = listOf(
                Vaccine("v1", "BCG", "Al nacer", true),
                Vaccine("v2", "Hepatitis B", "Al nacer", true),
                Vaccine("v3", "Neumococo conjugada (1ra)", "2 meses", true),
                Vaccine("v4", "Quíntuple pentavalente (1ra)", "2 meses", true),
                Vaccine("v5", "IPV/Salk (1ra)", "2 meses", true),
                Vaccine("v6", "Rotavirus (1ra)", "2 meses", true),
                Vaccine("v7", "Neumococo conjugada (2da)", "4 meses", true),
                Vaccine("v8", "Quíntuple pentavalente (2da)", "4 meses", false),
                Vaccine("v9", "IPV/Salk (2da)", "4 meses", false),
                Vaccine("v10", "Rotavirus (2da)", "4 meses", false),
                Vaccine("v11", "Meningococo (1ra)", "3 meses", false),
                Vaccine("v12", "Meningococo (2da)", "5 meses", false),
                Vaccine("v13", "Gripe (1ra)", "6 meses", false),
                Vaccine("v14", "Quíntuple pentavalente (3ra)", "6 meses", false),
                Vaccine("v15", "Hepatitis A", "12 meses", false),
                Vaccine("v16", "Triple viral (SRP) 1ra", "12 meses", false),
                Vaccine("v17", "Varicela", "15 meses", false)
            )
        }
    }

    fun addAppointment(context: Context, appointment: Appointment) {
        val current = _appointments.value?.toMutableList() ?: mutableListOf()
        current.add(appointment)
        _appointments.value = current
        saveAppointments(context)
    }

    fun removeAppointment(context: Context, position: Int) {
        val current = _appointments.value?.toMutableList() ?: return
        if (position in current.indices) {
            current.removeAt(position)
            _appointments.value = current
            saveAppointments(context)
        }
    }

    fun toggleVaccine(context: Context, position: Int) {
        val current = _vaccines.value?.toMutableList() ?: return
        if (position in current.indices) {
            val vaccine = current[position]
            current[position] = vaccine.copy(applied = !vaccine.applied)
            _vaccines.value = current
            saveVaccines(context)
        }
    }

    private fun saveAppointments(context: Context) {
        val prefs = context.getSharedPreferences("medical_data", Context.MODE_PRIVATE)
        val arr = JSONArray()
        _appointments.value?.forEach { appt ->
            arr.put(JSONObject().apply {
                put("id", appt.id)
                put("title", appt.title)
                put("date", appt.date)
                put("notes", appt.notes)
            })
        }
        prefs.edit().putString("appointments", arr.toString()).apply()
    }

    private fun saveVaccines(context: Context) {
        val prefs = context.getSharedPreferences("medical_data", Context.MODE_PRIVATE)
        val arr = JSONArray()
        _vaccines.value?.forEach { vac ->
            arr.put(JSONObject().apply {
                put("id", vac.id)
                put("name", vac.name)
                put("scheduled_age", vac.scheduledAge)
                put("applied", vac.applied)
                put("applied_date", vac.appliedDate)
            })
        }
        prefs.edit().putString("vaccines", arr.toString()).apply()
    }
}
