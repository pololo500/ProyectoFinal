package com.example.aplicacionparacelular.network

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
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

    private val executor = Executors.newScheduledThreadPool(2)
    private val mainHandler = Handler(Looper.getMainLooper())
    private var pollingFuture: ScheduledFuture<*>? = null

    /** Indica si init() ya fue llamado para evitar registrar observers duplicados. */
    private var initialized = false

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

        val appContext = context.applicationContext
        RobotApiClient.init(appContext)

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
                    RobotApiClient.setRobotAddress(appContext, robot.ip, robot.port)
                    startPolling()
                }
            }
            RobotDiscovery.startScan()
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

    // ------------------------------------------------------------------
    // Utilidad
    // ------------------------------------------------------------------

    private fun postToMain(action: () -> Unit) {
        mainHandler.post(action)
    }
}
