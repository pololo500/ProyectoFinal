package com.example.aplicacionparacelular.notifications

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        ReminderScheduler.restoreAll(context)
        try {
            TeoAlertPollService.start(context)
        } catch (_: Exception) {
            // Android puede bloquear FGS justo al arrancar el teléfono.
        }
    }
}
