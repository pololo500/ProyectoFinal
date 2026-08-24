package com.example.aplicacionparacelular.network

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/**
 * Gestor de la conexión con la Raspberry Pi.
 *
 * Mantiene un polling periódico del estado del robot y expone LiveData
 * reactivos que los Fragments pueden observar para actualizar la UI.
 *
 * Flujo de conexión:
 * 1. init() carga la IP guardada en SharedPreferences.
 * 2. Si no hay IP, inicia descubrimiento automático (UDP beacon + fallback HTTP).
 * 3. Cuando se configura una IP, arranca el polling automáticamente.
 * 4. El polling consulta /api/status cada N segundos y actualiza los LiveData.
 */
object RobotConnectionManager {

    private const val TAG = "RobotConnMgr"
    private const val CHANNEL_ID = "teo_parent_alerts"

    private val executor = Executors.newScheduledThreadPool(2)
    private val mainHandler = Handler(Looper.getMainLooper())
    private var pollingFuture: ScheduledFuture<*>? = null

    private var appContext: Context? = null
    private var initialized = false

    private val _parentAlerts = MutableLiveData<List<String>>(emptyList())
    val parentAlerts: LiveData<List<String>> = _parentAlerts

    private val recentAlerts = mutableListOf<String>()

    // ------------------------------------------------------------------
    // LiveData observables
    // ------------------------------------------------------------------

    private val _isConnected = MutableLiveData(false)
    val isConnected: LiveData<Boolean> = _isConnected

    private val _robotStatus = MutableLiveData<JSONObject?>()
    val robotStatus: LiveData<JSONObject?> = _robotStatus

    private val _lastError = MutableLiveData<String?>()
    val lastError: LiveData<String?> = _lastError

    // ------------------------------------------------------------------
    // Inicialización y Polling
    // ------------------------------------------------------------------

    /**
     * Inicializa el manager y el cliente API.
     * Debe llamarse una vez desde Application.onCreate() o MainActivity.
     * Si no hay IP configurada, intenta descubrir el robot automáticamente.
     *
     * Es seguro llamar múltiples veces — solo la primera tiene efecto.
     */
    fun init(context: Context) {
        if (initialized) {
            Log.d(TAG, "init() ya fue llamado, ignorando llamada duplicada")
            return
        }
        initialized = true

        val ctx = context.applicationContext
        appContext = ctx
        RobotApiClient.init(ctx)
        ensureNotificationChannel(ctx)

        if (RobotApiClient.isConfigured()) {
            // Ya tenemos IP guardada, arrancar polling de inmediato
            Log.d(TAG, "IP ya configurada, arrancando polling")
            startPolling()
        } else {
            // No hay IP guardada — iniciar descubrimiento automático
            Log.d(TAG, "No hay IP configurada, iniciando descubrimiento automático")

            RobotDiscovery.discoveredRobot.observeForever { robot ->
                if (robot != null && !RobotApiClient.isConfigured()) {
                    Log.d(TAG, "Robot descubierto: ${robot.ip}:${robot.port} (${robot.deviceName})")
                    RobotApiClient.setRobotAddress(ctx, robot.ip, robot.port)
                    startPolling()
                }
            }
            RobotDiscovery.startScan(ctx)
        }
    }

    /**
     * Configura manualmente la IP del robot y arranca el polling.
     * Usar desde la UI de configuración cuando el usuario ingresa la IP.
     */
    fun connectManually(context: Context, ip: String, port: Int = 8080) {
        Log.d(TAG, "Conexión manual a $ip:$port")
        RobotApiClient.setRobotAddress(context, ip, port)
        startPolling()
    }

    /**
     * Inicia el polling periódico del estado del robot.
     * El intervalo por defecto es de 5 segundos.
     */
    fun startPolling(intervalSeconds: Long = 5) {
        if (!RobotApiClient.isConfigured()) {
            Log.d(TAG, "startPolling() ignorado: no hay IP configurada")
            return
        }
        stopPolling()
        Log.d(TAG, "Polling iniciado (cada ${intervalSeconds}s)")
        pollingFuture = executor.scheduleWithFixedDelay(
            { pollStatus() },
            0,
            intervalSeconds,
            TimeUnit.SECONDS
        )
    }

    /**
     * Detiene el polling periódico.
     */
    fun stopPolling() {
        pollingFuture?.cancel(false)
        pollingFuture = null
    }

    private fun pollStatus() {
        if (!RobotApiClient.isConfigured()) {
            postToMain { _isConnected.value = false }
            return
        }

        when (val result = RobotApiClient.getStatus()) {
            is ApiResult.Success -> {
                postToMain {
                    _isConnected.value = true
                    _robotStatus.value = result.data
                    _lastError.value = null
                }
                pollNotifications()
            }
            is ApiResult.Error -> {
                Log.d(TAG, "Poll falló: ${result.message}")
                postToMain {
                    _isConnected.value = false
                    _robotStatus.value = null
                    _lastError.value = result.message
                }
            }
        }
    }

    // ------------------------------------------------------------------
    // Operaciones asíncronas (ejecutadas en background)
    // ------------------------------------------------------------------

    /**
     * Ejecuta una llamada API en background y llama al callback en el main thread.
     */
    fun <T> executeAsync(
        call: () -> ApiResult<T>,
        onResult: (ApiResult<T>) -> Unit
    ) {
        executor.execute {
            val result = call()
            postToMain { onResult(result) }
        }
    }

    /**
     * Envía una señal de celebración al robot.
     */
    fun celebrate(onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.postCelebrate() }, onResult)
    }

    /**
     * Enciende o apaga el robot.
     */
    fun setPower(powerOn: Boolean, onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.postPower(powerOn) }, onResult)
    }

    /**
     * Actualiza la configuración sensorial del robot.
     */
    fun updateConfig(volumeLimit: Int, brightness: Float, onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.postConfig(volumeLimit, brightness) }, onResult)
    }

    /**
     * Activa/desactiva el modo noche.
     */
    fun setNightMode(enabled: Boolean, onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.postNightMode(enabled) }, onResult)
    }

    /**
     * Obtiene la telemetría del día actual.
     */
    fun fetchTelemetryToday(onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.getTelemetryToday() }, onResult)
    }

    /**
     * Obtiene la telemetría de una fecha.
     */
    fun fetchTelemetry(date: String, onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.getTelemetry(date) }, onResult)
    }

    /**
     * Obtiene las rutinas configuradas.
     */
    fun fetchRoutines(onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.getRoutines() }, onResult)
    }

    /**
     * Actualiza las rutinas en el robot.
     */
    fun updateRoutines(routinesJson: JSONObject, onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.postRoutines(routinesJson) }, onResult)
    }

    /**
     * Obtiene la lista de canciones del robot.
     */
    fun fetchMusic(onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.getMusic() }, onResult)
    }

    /**
     * Sube una canción al robot.
     */
    fun uploadMusic(filename: String, data: ByteArray, onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.uploadMusic(filename, data) }, onResult)
    }

    /**
     * Elimina una canción del robot.
     */
    fun deleteMusic(filename: String, onResult: (ApiResult<JSONObject>) -> Unit) {
        executeAsync({ RobotApiClient.deleteMusic(filename) }, onResult)
    }

    /**
     * Reproduce una canción en el robot.
     */
    fun playMusic(filename: String? = null, onResult: (ApiResult<JSONObject>) -> Unit = {}) {
        executeAsync({ RobotApiClient.playMusic(filename) }, onResult)
    }

    /**
     * Detiene la reproducción de música en el robot.
     */
    fun stopMusic(onResult: (ApiResult<JSONObject>) -> Unit = {}) {
        executeAsync({ RobotApiClient.stopMusic() }, onResult)
    }

    // ------------------------------------------------------------------
    // Notificaciones Raspberry → celular
    // ------------------------------------------------------------------

    private fun pollNotifications() {
        when (val result = RobotApiClient.getNotifications()) {
            is ApiResult.Success -> {
                val arr = result.data.optJSONArray("notifications") ?: return
                if (arr.length() == 0) return
                val incoming = mutableListOf<String>()
                for (i in 0 until arr.length()) {
                    val obj = arr.optJSONObject(i) ?: continue
                    val type = obj.optString("type", "aviso")
                    val message = obj.optString("message", "")
                    if (message.isBlank()) continue
                    val line = formatAlert(type, message)
                    incoming.add(line)
                    showSystemNotification(type, message)
                }
                if (incoming.isEmpty()) return
                postToMain {
                    recentAlerts.addAll(0, incoming)
                    while (recentAlerts.size > 20) {
                        recentAlerts.removeAt(recentAlerts.lastIndex)
                    }
                    _parentAlerts.value = recentAlerts.toList()
                }
            }
            is ApiResult.Error -> {
                Log.d(TAG, "Poll notificaciones falló: ${result.message}")
            }
        }
    }

    private fun formatAlert(type: String, message: String): String {
        val prefix = when (type.lowercase()) {
            "crisis" -> "⚠️ Crisis"
            "pedido" -> "📞 Pedido"
            "musica" -> "🎵 Música"
            "logro" -> "🎉 Logro"
            "vocabulario" -> "📚 Vocabulario"
            else -> "ℹ️ Aviso"
        }
        return "$prefix: $message"
    }

    private fun ensureNotificationChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Avisos de TEO",
            NotificationManager.IMPORTANCE_HIGH
        )
        channel.description = "Crisis, pedidos del nene, música, vocabulario y logros"
        manager.createNotificationChannel(channel)
    }

    private fun showSystemNotification(type: String, message: String) {
        val context = appContext ?: return
        val title = when (type.lowercase()) {
            "crisis" -> "TEO: atención recomendada"
            "pedido" -> "TEO: el nene te necesita"
            "musica" -> "TEO está reproduciendo música"
            "logro" -> "TEO: el nene logró algo"
            "vocabulario" -> "TEO: palabras nuevas"
            else -> "Aviso de TEO"
        }
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(message))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .build()
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify((System.currentTimeMillis() % Int.MAX_VALUE).toInt(), notification)
    }

    // ------------------------------------------------------------------
    // Utilidad
    // ------------------------------------------------------------------

    private fun postToMain(action: () -> Unit) {
        mainHandler.post(action)
    }
}
