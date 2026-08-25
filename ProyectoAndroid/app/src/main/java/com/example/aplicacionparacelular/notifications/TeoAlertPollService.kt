package com.example.aplicacionparacelular.notifications

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import com.example.aplicacionparacelular.network.RobotConnectionManager

/**
 * Mantiene el poll de /api/notifications aunque la Activity se cierre.
 * Sin FCM: es un servicio local en la misma red WiFi que el peluche.
 */
class TeoAlertPollService : Service() {

    override fun onCreate() {
        super.onCreate()
        AppNotificationHelper.ensureChannels(this)
        val notification = AppNotificationHelper.foregroundBuilder(this).build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                FOREGROUND_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            startForeground(FOREGROUND_ID, notification)
        }
        RobotConnectionManager.init(this)
        RobotConnectionManager.startPolling(8)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val FOREGROUND_ID = 71001

        fun start(context: Context) {
            val intent = Intent(context, TeoAlertPollService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }
}
