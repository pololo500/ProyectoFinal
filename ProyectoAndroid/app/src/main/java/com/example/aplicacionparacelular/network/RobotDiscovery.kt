package com.example.aplicacionparacelular.network

import android.content.Context
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.URL

/**
 * Descubre automáticamente la Raspberry Pi en la red local escuchando
 * beacons UDP que el robot emite cada 3 segundos en el puerto 5555.
 *
 * El beacon contiene un JSON con:
 * - device_id: "micompanero_robot"
 * - device_name: nombre del dispositivo
 * - api_port: puerto del servidor REST
 * - local_ip: IP del robot en la red local
 *
 * Cuando corre en el emulador de Android Studio, el beacon UDP no llega
 * (red virtual aislada), así que se prueba automáticamente la IP especial
 * 10.0.2.2 (host del emulador) como fallback.
 */
object RobotDiscovery {

    private const val TAG = "RobotDiscovery"
    private const val BEACON_PORT = 5555
    private const val LISTEN_TIMEOUT_MS = 8000  // Escuchar máximo 8 segundos

    /** IP especial que el emulador de Android Studio mapea al host. */
    private const val EMULATOR_HOST_IP = "10.0.2.2"
    private const val DEFAULT_API_PORT = 8080

    /**
     * Resultado del descubrimiento.
     */
    data class DiscoveredRobot(
        val ip: String,
        val port: Int,
        val deviceName: String,
        val deviceId: String
    )

    private val _discoveredRobot = MutableLiveData<DiscoveredRobot?>()
    val discoveredRobot: LiveData<DiscoveredRobot?> = _discoveredRobot

    private val _isScanning = MutableLiveData(false)
    val isScanning: LiveData<Boolean> = _isScanning

    private val _scanError = MutableLiveData<String?>()
    val scanError: LiveData<String?> = _scanError

    private val mainHandler = Handler(Looper.getMainLooper())

    @Volatile
    private var scanThread: Thread? = null

    /** Contexto de la aplicación, necesario para adquirir el MulticastLock. */
    private var appContext: Context? = null

    /** Lock que impide que el chip WiFi descarte paquetes multicast/broadcast. */
    private var multicastLock: WifiManager.MulticastLock? = null

    /**
     * Detecta si la app está corriendo en un emulador de Android Studio.
     *
     * Usa varias heurísticas del Build: fingerprint genérico, modelo "sdk",
     * hardware "goldfish"/"ranchu", etc.
     */
    fun isEmulator(): Boolean {
        return (Build.FINGERPRINT.startsWith("generic")
                || Build.FINGERPRINT.startsWith("unknown")
                || Build.MODEL.contains("google_sdk", ignoreCase = true)
                || Build.MODEL.contains("Emulator", ignoreCase = true)
                || Build.MODEL.contains("Android SDK built for x86", ignoreCase = true)
                || Build.MANUFACTURER.contains("Genymotion", ignoreCase = true)
                || Build.BRAND.startsWith("generic") && Build.DEVICE.startsWith("generic")
                || Build.PRODUCT.contains("sdk", ignoreCase = true)
                || Build.HARDWARE.contains("goldfish", ignoreCase = true)
                || Build.HARDWARE.contains("ranchu", ignoreCase = true))
    }

    /**
     * Inicia un escaneo de la red local buscando el beacon UDP del robot.
     *
     * Si detecta que corre en un emulador, primero intenta conectar
     * directamente a 10.0.2.2:8080 (el host del emulador), ya que los
     * broadcasts UDP no atraviesan la red virtual del emulador.
     *
     * El escaneo se detiene automáticamente cuando encuentra un robot
     * o cuando se agota el timeout.
     */
    fun startScan(context: Context? = null) {
        if (_isScanning.value == true) return

        // Guardar el contexto de la aplicación para el MulticastLock
        if (context != null) {
            appContext = context.applicationContext
        }

        _isScanning.postValue(true)
        _scanError.postValue(null)
        _discoveredRobot.postValue(null)

        scanThread = Thread({
            // En el emulador, intentar primero la IP del host directamente
            if (isEmulator()) {
                Log.d(TAG, "Emulador detectado, intentando 10.0.2.2:$DEFAULT_API_PORT...")
                if (tryDirectConnection(EMULATOR_HOST_IP, DEFAULT_API_PORT)) {
                    return@Thread
                }
                Log.d(TAG, "Conexión directa a 10.0.2.2 falló, intentando beacon UDP...")
            }

            // Adquirir MulticastLock para que el chip WiFi no descarte
            // los paquetes broadcast/multicast (beacons UDP del peluche).
            // Sin esto, en celulares físicos el receive() siempre da timeout.
            acquireMulticastLock()

            // Intentar descubrimiento por beacon UDP (funciona en red real)
            var socket: DatagramSocket? = null
            try {
                socket = DatagramSocket(BEACON_PORT)
                socket.broadcast = true
                socket.soTimeout = LISTEN_TIMEOUT_MS
                socket.reuseAddress = true

                val buffer = ByteArray(1024)
                val packet = DatagramPacket(buffer, buffer.size)

                // Esperar un beacon
                socket.receive(packet)

                val data = String(packet.data, 0, packet.length, Charsets.UTF_8)
                val json = JSONObject(data)

                val deviceId = json.optString("device_id", "")
                if (deviceId == "micompanero_robot") {
                    // Usar la IP del paquete recibido (más confiable que la
                    // IP que reporta el beacon, por si hay NAT o multi-homed)
                    val ip = json.optString("local_ip", packet.address.hostAddress ?: "")
                    val port = json.optInt("api_port", DEFAULT_API_PORT)
                    val name = json.optString("device_name", "Peluche")

                    val robot = DiscoveredRobot(
                        ip = ip.ifBlank { packet.address.hostAddress ?: "" },
                        port = port,
                        deviceName = name,
                        deviceId = deviceId
                    )

                    mainHandler.post {
                        _discoveredRobot.value = robot
                        _isScanning.value = false
                    }
                    return@Thread
                }

                // Si el beacon no es del robot esperado
                mainHandler.post {
                    _scanError.value = "Dispositivo desconocido encontrado"
                    _isScanning.value = false
                }

            } catch (e: java.net.SocketTimeoutException) {
                // Beacon no recibido. Si no estamos en emulador (ya intentamos
                // arriba), intentar la IP del host por si acaso.
                if (!isEmulator() && tryDirectConnection(EMULATOR_HOST_IP, DEFAULT_API_PORT)) {
                    return@Thread
                }

                mainHandler.post {
                    _scanError.value = "No se encontró el peluche en la red. Ingresá la IP manualmente."
                    _isScanning.value = false
                }
            } catch (e: Exception) {
                mainHandler.post {
                    _scanError.value = "Error de red: ${e.message}. Ingresá la IP manualmente."
                    _isScanning.value = false
                }
            } finally {
                try { socket?.close() } catch (_: Exception) {}
                releaseMulticastLock()
            }
        }, "RobotDiscovery")

        scanThread?.isDaemon = true
        scanThread?.start()
    }

    /**
     * Intenta una conexión HTTP directa a la IP y puerto dados,
     * haciendo un GET /api/status. Si responde correctamente,
     * publica el robot descubierto y retorna true.
     */
    private fun tryDirectConnection(ip: String, port: Int): Boolean {
        return try {
            val url = URL("http://$ip:$port/api/status")
            val conn = url.openConnection() as HttpURLConnection
            conn.connectTimeout = 3000
            conn.readTimeout = 3000
            conn.requestMethod = "GET"

            val code = conn.responseCode
            if (code == 200) {
                val robot = DiscoveredRobot(
                    ip = ip,
                    port = port,
                    deviceName = "MiCompañero Peluche (local)",
                    deviceId = "micompanero_robot"
                )
                mainHandler.post {
                    _discoveredRobot.value = robot
                    _isScanning.value = false
                }
                conn.disconnect()
                Log.d(TAG, "Conexión directa exitosa a $ip:$port")
                true
            } else {
                conn.disconnect()
                false
            }
        } catch (e: Exception) {
            Log.d(TAG, "Conexión directa a $ip:$port falló: ${e.message}")
            false
        }
    }

    /**
     * Cancela un escaneo en curso.
     */
    fun stopScan() {
        scanThread?.interrupt()
        scanThread = null
        releaseMulticastLock()
        _isScanning.postValue(false)
    }

    // ------------------------------------------------------------------
    // MulticastLock helpers
    // ------------------------------------------------------------------

    /**
     * Adquiere un [WifiManager.MulticastLock].
     *
     * Por defecto, Android desactiva la recepción de paquetes multicast/broadcast
     * en el chip WiFi para ahorrar batería. El beacon UDP que emite el peluche
     * es un broadcast, así que sin este lock el [DatagramSocket.receive] nunca
     * recibe nada y siempre da timeout en celulares físicos.
     */
    private fun acquireMulticastLock() {
        try {
            val ctx = appContext ?: return
            val wifiMgr = ctx.getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return
            val lock = wifiMgr.createMulticastLock("RobotDiscovery")
            lock.setReferenceCounted(true)
            lock.acquire()
            multicastLock = lock
            Log.d(TAG, "MulticastLock adquirido")
        } catch (e: Exception) {
            Log.w(TAG, "No se pudo adquirir MulticastLock: ${e.message}")
        }
    }

    /**
     * Libera el [WifiManager.MulticastLock] si estaba adquirido,
     * para no consumir batería innecesariamente.
     */
    private fun releaseMulticastLock() {
        try {
            multicastLock?.let {
                if (it.isHeld) {
                    it.release()
                    Log.d(TAG, "MulticastLock liberado")
                }
            }
            multicastLock = null
        } catch (e: Exception) {
            Log.w(TAG, "Error al liberar MulticastLock: ${e.message}")
        }
    }
}
