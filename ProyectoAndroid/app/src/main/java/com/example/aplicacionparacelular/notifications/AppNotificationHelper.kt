package com.example.aplicacionparacelular.notifications

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.example.aplicacionparacelular.MainActivity

/**
 * Canales y avisos locales (vacunas, rutinas, peluche).
 * No usa FCM: son notificaciones del sistema en el celular.
 */
object AppNotificationHelper {

    const val CHANNEL_PELUCHE = "teo_peluche"
    const val CHANNEL_RUTINA = "teo_rutina"
    const val CHANNEL_VACUNA = "teo_vacuna"
    const val CHANNEL_FOREGROUND = "teo_escucha_avisos"
    private const val FOREGROUND_OPEN = 71000

    fun ensureChannels(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_PELUCHE, "Avisos del peluche", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Crisis, pedidos, logros y vocabulario que manda TEO"
            }
        )
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_RUTINA, "Próximas rutinas", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "Recordatorios de horarios de rutina"
            }
        )
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_VACUNA, "Vacunación", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "Turnos y vacunas pendientes"
            }
        )
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_FOREGROUND, "Conexión con TEO", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Mantiene los avisos del peluche en segundo plano"
                setShowBadge(false)
            }
        )
    }

    fun show(
        context: Context,
        channelId: String,
        notificationId: Int,
        title: String,
        message: String,
        highPriority: Boolean = false,
    ) {
        ensureChannels(context)
        val open = PendingIntent.getActivity(
            context,
            notificationId,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(message))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setPriority(
                if (highPriority) NotificationCompat.PRIORITY_HIGH
                else NotificationCompat.PRIORITY_DEFAULT
            )
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(notificationId, builder.build())
    }

    fun foregroundBuilder(context: Context): NotificationCompat.Builder {
        ensureChannels(context)
        return NotificationCompat.Builder(context, CHANNEL_FOREGROUND)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("TEO está atento a avisos")
            .setContentText("Los avisos del peluche llegan aunque la app esté en segundo plano")
            .setContentIntent(
                PendingIntent.getActivity(
                    context,
                    FOREGROUND_OPEN,
                    Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
                )
            )
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
    }
}
