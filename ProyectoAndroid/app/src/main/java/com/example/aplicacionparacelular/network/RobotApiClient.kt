package com.example.aplicacionparacelular.network

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Cliente HTTP singleton para comunicarse con la API REST de la Raspberry Pi.
 *
 * Usa HttpURLConnection nativo de Android (sin dependencias externas).
 * Todas las operaciones de red se ejecutan en hilos de fondo; los métodos
 * retornan el resultado directamente y deben ser llamados desde coroutines
 * o hilos de fondo.
 */
object RobotApiClient {

    private const val PREFS_NAME = "robot_connection"
    private const val KEY_ROBOT_IP = "robot_ip"
    private const val KEY_ROBOT_PORT = "robot_port"
    private const val DEFAULT_PORT = 8080
    private const val CONNECT_TIMEOUT = 3000
    private const val READ_TIMEOUT = 10000

    private var baseUrl: String = ""

    /**
     * Inicializa el cliente con la IP guardada en SharedPreferences.
     */
    fun init(context: Context) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val ip = prefs.getString(KEY_ROBOT_IP, "") ?: ""
        val port = prefs.getInt(KEY_ROBOT_PORT, DEFAULT_PORT)
        if (ip.isNotBlank()) {
            baseUrl = "http://$ip:$port"
        }
    }

    /**
     * Configura la IP del robot y la persiste.
     */
    fun setRobotAddress(context: Context, ip: String, port: Int = DEFAULT_PORT) {
        baseUrl = "http://$ip:$port"
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit()
            .putString(KEY_ROBOT_IP, ip)
            .putInt(KEY_ROBOT_PORT, port)
            .apply()
    }

    fun getRobotIp(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_ROBOT_IP, "") ?: ""
    }

    fun isConfigured(): Boolean = baseUrl.isNotBlank()

    // ------------------------------------------------------------------
    // GET endpoints
    // ------------------------------------------------------------------

    /** Obtiene el estado actual del robot. */
    fun getStatus(): ApiResult<JSONObject> = doGet("/api/status")

    /** Obtiene la telemetría del día actual. */
    fun getTelemetryToday(): ApiResult<JSONObject> = doGet("/api/telemetry/today")

    /** Obtiene la telemetría de una fecha específica (YYYY-MM-DD). */
    fun getTelemetry(date: String): ApiResult<JSONObject> = doGet("/api/telemetry/$date")

    /** Obtiene la lista de rutinas configuradas. */
    fun getRoutines(): ApiResult<JSONObject> = doGet("/api/routines")

    /** Obtiene la lista de canciones. */
    fun getMusic(): ApiResult<JSONObject> = doGet("/api/music")

    // ------------------------------------------------------------------
    // POST endpoints
    // ------------------------------------------------------------------

    /** Envía la configuración sensorial al robot. */
    fun postConfig(volumeLimit: Int, brightness: Float): ApiResult<JSONObject> {
        val body = JSONObject().apply {
            put("volume_limit", volumeLimit)
            put("brightness", brightness.toDouble())
        }
        return doPost("/api/config", body)
    }

    /** Envía señal de celebración al robot. */
    fun postCelebrate(): ApiResult<JSONObject> =
        doPost("/api/celebrate", JSONObject())

    /** Activa o desactiva el modo noche. */
    fun postNightMode(enabled: Boolean): ApiResult<JSONObject> {
        val body = JSONObject().apply { put("enabled", enabled) }
        return doPost("/api/night-mode", body)
    }

    /** Enciende o apaga el robot. */
    fun postPower(powerOn: Boolean): ApiResult<JSONObject> {
        val body = JSONObject().apply { put("power_on", powerOn) }
        return doPost("/api/power", body)
    }

    /** Actualiza las rutinas en el robot. */
    fun postRoutines(routinesJson: JSONObject): ApiResult<JSONObject> =
        doPost("/api/routines", routinesJson)

    /** Sube un archivo de música al robot. */
    fun uploadMusic(filename: String, data: ByteArray): ApiResult<JSONObject> {
        if (!isConfigured()) return ApiResult.Error("Robot no configurado")
        return try {
            val url = URL("$baseUrl/api/music/upload")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = CONNECT_TIMEOUT
                readTimeout = 30000 // Upload puede tardar más
                setRequestProperty("Content-Type", "application/octet-stream")
                setRequestProperty("X-Filename", filename)
                doOutput = true
            }
            conn.outputStream.use { it.write(data) }
            readResponse(conn)
        } catch (e: Exception) {
            ApiResult.Error(e.message ?: "Error de conexión")
        }
    }

    // ------------------------------------------------------------------
    // DELETE endpoints
    // ------------------------------------------------------------------

    /** Elimina una canción del robot. */
    fun deleteMusic(filename: String): ApiResult<JSONObject> =
        doDelete("/api/music/$filename")

    // ------------------------------------------------------------------
    // Helpers HTTP
    // ------------------------------------------------------------------

    private fun doGet(path: String): ApiResult<JSONObject> {
        if (!isConfigured()) return ApiResult.Error("Robot no configurado")
        return try {
            val url = URL("$baseUrl$path")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = CONNECT_TIMEOUT
                readTimeout = READ_TIMEOUT
            }
            readResponse(conn)
        } catch (e: Exception) {
            ApiResult.Error(e.message ?: "Error de conexión")
        }
    }

    private fun doPost(path: String, body: JSONObject): ApiResult<JSONObject> {
        if (!isConfigured()) return ApiResult.Error("Robot no configurado")
        return try {
            val url = URL("$baseUrl$path")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = CONNECT_TIMEOUT
                readTimeout = READ_TIMEOUT
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                doOutput = true
            }
            val bodyBytes = body.toString().toByteArray(Charsets.UTF_8)
            conn.outputStream.use { it.write(bodyBytes) }
            readResponse(conn)
        } catch (e: Exception) {
            ApiResult.Error(e.message ?: "Error de conexión")
        }
    }

    private fun doDelete(path: String): ApiResult<JSONObject> {
        if (!isConfigured()) return ApiResult.Error("Robot no configurado")
        return try {
            val url = URL("$baseUrl$path")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "DELETE"
                connectTimeout = CONNECT_TIMEOUT
                readTimeout = READ_TIMEOUT
            }
            readResponse(conn)
        } catch (e: Exception) {
            ApiResult.Error(e.message ?: "Error de conexión")
        }
    }

    private fun readResponse(conn: HttpURLConnection): ApiResult<JSONObject> {
        return try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val reader = BufferedReader(InputStreamReader(stream, Charsets.UTF_8))
            val response = reader.readText()
            reader.close()
            conn.disconnect()

            if (code in 200..299) {
                ApiResult.Success(JSONObject(response))
            } else {
                val errorMsg = try {
                    JSONObject(response).optString("error", "Error $code")
                } catch (_: Exception) {
                    "Error HTTP $code"
                }
                ApiResult.Error(errorMsg)
            }
        } catch (e: Exception) {
            conn.disconnect()
            ApiResult.Error(e.message ?: "Error al leer respuesta")
        }
    }
}

/** Resultado genérico de una llamada a la API. */
sealed class ApiResult<out T> {
    data class Success<T>(val data: T) : ApiResult<T>()
    data class Error(val message: String) : ApiResult<Nothing>()
}
