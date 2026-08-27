package com.example.aplicacionparacelular.notifications

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.util.Calendar
import java.util.Locale

/**
 * Agenda alarmas locales (sin internet) para vacunas y rutinas.
 * Persistimos un JSON mínimo para rearmarlas tras un reinicio.
 */
object ReminderScheduler {

    private const val PREFS = "teo_reminders"
    private const val KEY_ROUTINES = "routines_json"
    private const val KEY_VACCINES = "vaccines_json"
    private const val KEY_APPOINTMENTS = "appointments_json"
    private const val BASE_ROUTINE = 42000
    private const val BASE_VACCINE = 43000
    private const val BASE_APPT = 44000

    fun restoreAll(context: Context) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        scheduleRoutinesFromJson(context, prefs.getString(KEY_ROUTINES, "[]") ?: "[]")
        scheduleVaccinesFromJson(context, prefs.getString(KEY_VACCINES, "[]") ?: "[]")
        scheduleAppointmentsFromJson(context, prefs.getString(KEY_APPOINTMENTS, "[]") ?: "[]")
    }

    fun saveAndScheduleRoutines(
        context: Context,
        items: List<Triple<String, String, Int>>,
    ) {
        val arr = JSONArray()
        items.forEach { (id, name, minutesOfDay) ->
            arr.put(JSONObject().put("id", id).put("name", name).put("minutes", minutesOfDay))
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_ROUTINES, arr.toString()).apply()
        scheduleRoutinesFromJson(context, arr.toString())
    }

    fun saveAndScheduleVaccines(
        context: Context,
        items: List<VaccineReminder>,
    ) {
        val arr = JSONArray()
        items.forEach { v ->
            arr.put(
                JSONObject()
                    .put("id", v.id)
                    .put("name", v.name)
                    .put("dueDate", v.dueDateIso)
                    .put("applied", v.applied)
            )
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_VACCINES, arr.toString()).apply()
        scheduleVaccinesFromJson(context, arr.toString())
    }

    fun saveAndScheduleAppointments(
        context: Context,
        items: List<Pair<String, String>>,
    ) {
        val arr = JSONArray()
        items.forEach { (title, dateText) ->
            arr.put(JSONObject().put("title", title).put("date", dateText))
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_APPOINTMENTS, arr.toString()).apply()
        scheduleAppointmentsFromJson(context, arr.toString())
    }

    fun rescheduleRoutineFromIntent(context: Context, intent: Intent) {
        val hhmm = intent.getStringExtra(ReminderReceiver.EXTRA_ROUTINE_HHMM) ?: return
        val parts = hhmm.split(":")
        if (parts.size < 2) return
        val hour = parts[0].toIntOrNull() ?: return
        val minute = parts[1].toIntOrNull() ?: return
        val id = intent.getIntExtra(ReminderReceiver.EXTRA_ID, 0)
        val title = intent.getStringExtra(ReminderReceiver.EXTRA_TITLE) ?: "Rutina"
        val message = intent.getStringExtra(ReminderReceiver.EXTRA_MESSAGE) ?: return
        setAlarm(
            context,
            id,
            nextOccurrence(hour, minute),
            ReminderReceiver.KIND_RUTINA,
            title,
            message,
            String.format(Locale.US, "%02d:%02d", hour, minute),
        )
    }

    private fun scheduleRoutinesFromJson(context: Context, json: String) {
        val arr = JSONArray(json)
        for (i in 0 until arr.length()) {
            val obj = arr.optJSONObject(i) ?: continue
            val minutes = obj.optInt("minutes", -1)
            if (minutes < 0) continue
            val hour = minutes / 60
            val minute = minutes % 60
            val name = obj.optString("name", "Rutina")
            val id = BASE_ROUTINE + (obj.optString("id").hashCode() and 0x0FFF)
            setAlarm(
                context,
                id,
                nextOccurrence(hour, minute),
                ReminderReceiver.KIND_RUTINA,
                "TEO: rutina",
                "Se acerca $name (${String.format(Locale.US, "%02d:%02d", hour, minute)})",
                String.format(Locale.US, "%02d:%02d", hour, minute),
            )
        }
    }

    private fun scheduleVaccinesFromJson(context: Context, json: String) {
        val arr = JSONArray(json)
        for (i in 0 until arr.length()) {
            val obj = arr.optJSONObject(i) ?: continue
            val name = obj.optString("name")
            val applied = obj.optBoolean("applied")
            val due = obj.optString("dueDate")
            if (applied || due.isBlank()) continue
            val day = parseIsoDate(due) ?: continue
            val id = BASE_VACCINE + (obj.optString("id").hashCode() and 0x0FFF)
            val morning = day.clone() as Calendar
            morning.set(Calendar.HOUR_OF_DAY, 9)
            morning.set(Calendar.MINUTE, 0)
            morning.set(Calendar.SECOND, 0)
            if (morning.timeInMillis > System.currentTimeMillis()) {
                setAlarm(
                    context,
                    id,
                    morning,
                    ReminderReceiver.KIND_VACUNA,
                    "TEO: vacunación",
                    "Hoy toca la vacuna $name",
                    null,
                )
            }
            val eve = morning.clone() as Calendar
            eve.add(Calendar.DAY_OF_YEAR, -1)
            if (eve.timeInMillis > System.currentTimeMillis()) {
                setAlarm(
                    context,
                    id + 8000,
                    eve,
                    ReminderReceiver.KIND_VACUNA,
                    "TEO: vacunación mañana",
                    "Mañana es la vacuna $name",
                    null,
                )
            }
        }
    }

    private fun scheduleAppointmentsFromJson(context: Context, json: String) {
        val arr = JSONArray(json)
        for (i in 0 until arr.length()) {
            val obj = arr.optJSONObject(i) ?: continue
            val title = obj.optString("title")
            val whenCal = parseAppointmentDate(obj.optString("date")) ?: continue
            if (whenCal.timeInMillis <= System.currentTimeMillis()) continue
            val isVaccine = title.contains("vacun", ignoreCase = true)
            val kind = if (isVaccine) ReminderReceiver.KIND_VACUNA else ReminderReceiver.KIND_TURNO
            val channelTitle = if (isVaccine) "TEO: vacunación" else "TEO: turno médico"
            val id = BASE_APPT + (title.hashCode() and 0x0FFF)
            setAlarm(context, id, whenCal, kind, channelTitle, "$title · ${obj.optString("date")}", null)
            val hourBefore = whenCal.clone() as Calendar
            hourBefore.add(Calendar.HOUR_OF_DAY, -1)
            if (hourBefore.timeInMillis > System.currentTimeMillis()) {
                setAlarm(
                    context,
                    id + 9000,
                    hourBefore,
                    kind,
                    channelTitle,
                    "En una hora: $title",
                    null,
                )
            }
        }
    }

    private fun setAlarm(
        context: Context,
        requestCode: Int,
        whenCal: Calendar,
        kind: String,
        title: String,
        message: String,
        hhmm: String?,
    ) {
        val alarm = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val intent = Intent(context, ReminderReceiver::class.java).apply {
            action = ReminderReceiver.ACTION_REMINDER
            putExtra(ReminderReceiver.EXTRA_KIND, kind)
            putExtra(ReminderReceiver.EXTRA_TITLE, title)
            putExtra(ReminderReceiver.EXTRA_MESSAGE, message)
            putExtra(ReminderReceiver.EXTRA_ID, requestCode)
            if (hhmm != null) putExtra(ReminderReceiver.EXTRA_ROUTINE_HHMM, hhmm)
        }
        val pending = PendingIntent.getBroadcast(
            context,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val at = whenCal.timeInMillis
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !alarm.canScheduleExactAlarms()) {
                alarm.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending)
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                alarm.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending)
            } else {
                @Suppress("DEPRECATION")
                alarm.setExact(AlarmManager.RTC_WAKEUP, at, pending)
            }
        } catch (_: SecurityException) {
            alarm.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending)
        }
    }

    private fun nextOccurrence(hour: Int, minute: Int): Calendar {
        val cal = Calendar.getInstance()
        cal.set(Calendar.HOUR_OF_DAY, hour)
        cal.set(Calendar.MINUTE, minute)
        cal.set(Calendar.SECOND, 0)
        cal.set(Calendar.MILLISECOND, 0)
        if (cal.timeInMillis <= System.currentTimeMillis() + 15_000) {
            cal.add(Calendar.DAY_OF_YEAR, 1)
        }
        return cal
    }

    private fun parseIsoDate(iso: String): Calendar? {
        val parts = iso.split("-")
        if (parts.size < 3) return null
        val y = parts[0].toIntOrNull() ?: return null
        val m = parts[1].toIntOrNull() ?: return null
        val d = parts[2].toIntOrNull() ?: return null
        return Calendar.getInstance().apply {
            set(Calendar.YEAR, y)
            set(Calendar.MONTH, m - 1)
            set(Calendar.DAY_OF_MONTH, d)
            set(Calendar.HOUR_OF_DAY, 9)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
        }
    }

    fun parseAppointmentDate(text: String): Calendar? {
        val slash = Regex("""(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})""").find(text)
        if (slash != null) {
            val (d, m, y, h, min) = slash.destructured
            return Calendar.getInstance().apply {
                set(Calendar.YEAR, y.toInt())
                set(Calendar.MONTH, m.toInt() - 1)
                set(Calendar.DAY_OF_MONTH, d.toInt())
                set(Calendar.HOUR_OF_DAY, h.toInt())
                set(Calendar.MINUTE, min.toInt())
                set(Calendar.SECOND, 0)
            }
        }
        val months = mapOf(
            "enero" to 0, "febrero" to 1, "marzo" to 2, "abril" to 3,
            "mayo" to 4, "junio" to 5, "julio" to 6, "agosto" to 7,
            "septiembre" to 8, "octubre" to 9, "noviembre" to 10, "diciembre" to 11,
        )
        val named = Regex("""(\d{1,2})\s+de\s+([a-záéíóú]+).*?(\d{1,2}):(\d{2})""", RegexOption.IGNORE_CASE).find(text)
        if (named != null) {
            val (d, monthName, h, min) = named.destructured
            val month = months[monthName.lowercase(Locale("es"))] ?: return null
            val year = Calendar.getInstance().get(Calendar.YEAR)
            return Calendar.getInstance().apply {
                set(Calendar.YEAR, year)
                set(Calendar.MONTH, month)
                set(Calendar.DAY_OF_MONTH, d.toInt())
                set(Calendar.HOUR_OF_DAY, h.toInt())
                set(Calendar.MINUTE, min.toInt())
                set(Calendar.SECOND, 0)
            }
        }
        return null
    }

    data class VaccineReminder(
        val id: String,
        val name: String,
        val dueDateIso: String,
        val applied: Boolean,
    )
}
