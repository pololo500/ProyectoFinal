package com.example.aplicacionparacelular.network

import android.os.Handler
import android.os.Looper
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/**
 * Descubre automáticamente la Raspberry Pi en la red local escuchando
 * beacons UDP que el robot emite cada 3 segundos en el puerto 5555.
 *
 * El beacon contiene un JSON con:
 * - device_id: "micompanero_robot"
 * - device_name: nombre del dispositivo
 * - api_port: puerto del servidor REST
 * - local_ip: IP del robot en la red local
 */
object RobotDiscovery {

    private const val BEACON_PORT = 5555
    private const val LISTEN_TIMEOUT_MS = 8000  // Escuchar máximo 8 segundos

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

    /**
     * Inicia un escaneo de la red local buscando el beacon UDP del robot.
     * El escaneo se detiene automáticamente cuando encuentra un robot
     * o cuando se agota el timeout.
     */
    fun startScan() {
        if (_isScanning.value == true) return

        _isScanning.postValue(true)
        _scanError.postValue(null)
        _discoveredRobot.postValue(null)

        scanThread = Thread({
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
                    val port = json.optInt("api_port", 8080)
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
            }
        }, "RobotDiscovery")

        scanThread?.isDaemon = true
        scanThread?.start()
    }

    /**
     * Cancela un escaneo en curso.
     */
    fun stopScan() {
        scanThread?.interrupt()
        scanThread = null
        _isScanning.postValue(false)
    }
}
