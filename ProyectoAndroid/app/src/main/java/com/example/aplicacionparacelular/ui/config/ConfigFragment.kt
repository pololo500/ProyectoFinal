package com.example.aplicacionparacelular.ui.config

import android.content.Context
import android.net.wifi.WifiManager
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import com.example.aplicacionparacelular.BuildConfig
import com.example.aplicacionparacelular.databinding.FragmentConfigBinding
import com.example.aplicacionparacelular.network.RobotApiClient
import com.example.aplicacionparacelular.network.RobotConnectionManager
import com.example.aplicacionparacelular.network.RobotDiscovery
import com.google.android.material.snackbar.Snackbar
import java.net.Inet4Address
import java.net.NetworkInterface

class ConfigFragment : Fragment() {

    private var _binding: FragmentConfigBinding? = null
    private val binding get() = _binding!!
    private lateinit var viewModel: ConfigViewModel

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        viewModel = ViewModelProvider(this).get(ConfigViewModel::class.java)
        _binding = FragmentConfigBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        setupDebugBanner()
        setupConnectionSection()
        setupSensorySection()
        setupNightModeSection()
        setupStatusObservers()

        if (RobotApiClient.isConfigured()) {
            viewModel.loadFromRobot()
        }
    }

    private fun setupDebugBanner() {
        if (BuildConfig.DEBUG) {
            binding.debugInfoBanner.visibility = View.VISIBLE

            // Get phone's WiFi IP
            val phoneIp = getDeviceIpAddress()
            binding.txtDebugPhoneIp.text = "📱 IP del celular: $phoneIp"

            // Show configured robot IP
            val configuredIp = RobotApiClient.getRobotIp(requireContext())
            binding.txtDebugConfiguredIp.text = if (configuredIp.isNotBlank()) {
                "🧸 IP configurada: $configuredIp"
            } else {
                "🧸 IP configurada: (ninguna)"
            }

            // Determine hint based on emulator vs real device
            val isEmulator = RobotDiscovery.isEmulator()
            binding.txtDebugHint.text = if (isEmulator) {
                "💡 Estás en emulador → usá 10.0.2.2 como IP del robot"
            } else {
                "💡 Abrí la consola del Python y buscá la IP que aparece en el recuadro del servidor. Ingresala abajo."
            }

            // Try to fetch server info from configured IP
            if (configuredIp.isNotBlank()) {
                fetchServerInfo(configuredIp)
            } else {
                binding.txtDebugServerIp.text = "🖥️ IP del servidor Python: (no configurada, ingresá la IP primero)"
            }
        } else {
            binding.debugInfoBanner.visibility = View.GONE
        }
    }

    private fun getDeviceIpAddress(): String {
        try {
            // Try WiFi manager first
            @Suppress("DEPRECATION")
            val wifiManager = requireContext().applicationContext.getSystemService(android.content.Context.WIFI_SERVICE) as? WifiManager
            if (wifiManager != null) {
                val ipInt = wifiManager.connectionInfo.ipAddress
                if (ipInt != 0) {
                    return String.format("%d.%d.%d.%d",
                        ipInt and 0xff, (ipInt shr 8) and 0xff,
                        (ipInt shr 16) and 0xff, (ipInt shr 24) and 0xff)
                }
            }
            // Fallback: enumerate network interfaces
            val interfaces = NetworkInterface.getNetworkInterfaces()
            while (interfaces.hasMoreElements()) {
                val iface = interfaces.nextElement()
                val addresses = iface.inetAddresses
                while (addresses.hasMoreElements()) {
                    val addr = addresses.nextElement()
                    if (!addr.isLoopbackAddress && addr is Inet4Address) {
                        return addr.hostAddress ?: "?.?.?.?"
                    }
                }
            }
        } catch (_: Exception) { }
        return "No disponible"
    }

    private fun fetchServerInfo(robotIp: String) {
        binding.txtDebugServerIp.text = "🖥️ IP del servidor Python: buscando..."
        Thread {
            try {
                val url = java.net.URL("http://$robotIp:8080/api/server-info")
                val conn = url.openConnection() as java.net.HttpURLConnection
                conn.connectTimeout = 2000
                conn.readTimeout = 2000
                conn.requestMethod = "GET"
                val code = conn.responseCode
                if (code == 200) {
                    val body = conn.inputStream.bufferedReader().readText()
                    conn.disconnect()
                    val json = org.json.JSONObject(body)
                    val serverIp = json.optString("server_ip", "?")
                    val serverPort = json.optInt("server_port", 8080)
                    activity?.runOnUiThread {
                        if (_binding != null) {
                            binding.txtDebugServerIp.text = "🖥️ IP del servidor Python: $serverIp:$serverPort"
                            binding.txtDebugConnectionResult.visibility = View.VISIBLE
                            binding.txtDebugConnectionResult.text = "✅ Conexión exitosa al servidor Python"
                            binding.txtDebugConnectionResult.setTextColor(0xFF4CAF50.toInt())
                        }
                    }
                } else {
                    conn.disconnect()
                    activity?.runOnUiThread {
                        if (_binding != null) {
                            binding.txtDebugServerIp.text = "🖥️ IP del servidor Python: error HTTP $code"
                            binding.txtDebugConnectionResult.visibility = View.VISIBLE
                            binding.txtDebugConnectionResult.text = "❌ Servidor respondió con error $code"
                            binding.txtDebugConnectionResult.setTextColor(0xFFF44336.toInt())
                        }
                    }
                }
            } catch (e: Exception) {
                activity?.runOnUiThread {
                    if (_binding != null) {
                        binding.txtDebugServerIp.text = "🖥️ IP del servidor Python: no alcanzable"
                        binding.txtDebugConnectionResult.visibility = View.VISIBLE
                        binding.txtDebugConnectionResult.text = "❌ No se puede conectar a $robotIp:8080 — ${e.message}"
                        binding.txtDebugConnectionResult.setTextColor(0xFFF44336.toInt())
                    }
                }
            }
        }.start()
    }

    // ------------------------------------------------------------------
    // Connection & Discovery
    // ------------------------------------------------------------------

    private fun setupConnectionSection() {
        // Show current IP if already configured
        val currentIp = RobotApiClient.getRobotIp(requireContext())
        binding.editRobotIp.setText(currentIp)

        // If running on emulator and no IP configured, suggest 10.0.2.2
        if (currentIp.isBlank() && RobotDiscovery.isEmulator()) {
            binding.editRobotIp.hint = "10.0.2.2 (emulador detectado)"
        }

        // Manual connect button
        binding.btnSaveIp.setOnClickListener {
            var ip = binding.editRobotIp.text.toString().trim()
            // If empty and on emulator, use 10.0.2.2 by default
            if (ip.isBlank() && RobotDiscovery.isEmulator()) {
                ip = "10.0.2.2"
                binding.editRobotIp.setText(ip)
            }
            if (ip.isNotBlank()) {
                connectToRobot(ip)
            }
        }

        // Auto-scan button
        binding.btnAutoScan.setOnClickListener {
            RobotDiscovery.startScan(requireContext())
        }

        // Observe scanning state
        RobotDiscovery.isScanning.observe(viewLifecycleOwner) { scanning ->
            binding.btnAutoScan.isEnabled = !scanning
            binding.btnAutoScan.text = if (scanning) "🔍 Buscando peluche..." else "🔍 Buscar automáticamente"
            binding.progressScan.visibility = if (scanning) View.VISIBLE else View.GONE
        }

        // Observe discovered robot
        RobotDiscovery.discoveredRobot.observe(viewLifecycleOwner) { robot ->
            if (robot != null) {
                // Found the robot! Show confirmation and auto-connect
                binding.txtDiscoveryResult.visibility = View.VISIBLE
                binding.txtDiscoveryResult.text = "✅ Encontrado: ${robot.deviceName} (${robot.ip})"
                binding.editRobotIp.setText(robot.ip)

                // Auto-connect if not already connected
                if (!RobotApiClient.isConfigured() || RobotApiClient.getRobotIp(requireContext()) != robot.ip) {
                    connectToRobot(robot.ip, robot.port)
                }
            }
        }

        // Observe scan errors
        RobotDiscovery.scanError.observe(viewLifecycleOwner) { error ->
            if (error != null) {
                binding.txtDiscoveryResult.visibility = View.VISIBLE
                binding.txtDiscoveryResult.text = "⚠️ $error"
            }
        }

        // Connection status
        RobotConnectionManager.isConnected.observe(viewLifecycleOwner) { connected ->
            binding.txtConnectionStatus.text = if (connected) "🟢 Conectado" else "🔴 Desconectado"
        }

        // Show last error for debugging
        RobotConnectionManager.lastError.observe(viewLifecycleOwner) { error ->
            if (error != null && RobotConnectionManager.isConnected.value != true) {
                binding.txtDiscoveryResult.visibility = View.VISIBLE
                binding.txtDiscoveryResult.text = "⚠️ Error: $error"
            }
        }

        // Auto-scan on first visit if not configured
        if (!RobotApiClient.isConfigured()) {
            RobotDiscovery.startScan(requireContext())
        }
    }

    private fun connectToRobot(ip: String, port: Int = 8080) {
        RobotConnectionManager.connectManually(requireContext(), ip, port)
        Snackbar.make(binding.root, "Conectando a $ip:$port...", Snackbar.LENGTH_SHORT).show()
        viewModel.loadFromRobot()
        // Refresh debug info after connecting
        if (BuildConfig.DEBUG) {
            binding.txtDebugConfiguredIp.text = "🧸 IP configurada: $ip"
            fetchServerInfo(ip)
        }
    }

    // ------------------------------------------------------------------
    // Sensory Configuration
    // ------------------------------------------------------------------

    private fun setupSensorySection() {
        // Volume slider
        binding.sliderVolume.addOnChangeListener { _, value, fromUser ->
            if (fromUser) {
                viewModel.setVolumeLimit(value.toInt())
                binding.txtVolumeValue.text = "${value.toInt()}%"
            }
        }
        viewModel.volumeLimit.observe(viewLifecycleOwner) { value ->
            binding.sliderVolume.value = value.toFloat()
            binding.txtVolumeValue.text = "$value%"
        }

        // Brightness slider
        binding.sliderBrightness.addOnChangeListener { _, value, fromUser ->
            if (fromUser) {
                viewModel.setBrightness(value.toInt())
                binding.txtBrightnessValue.text = "${value.toInt()}%"
            }
        }
        viewModel.brightness.observe(viewLifecycleOwner) { value ->
            binding.sliderBrightness.value = value.toFloat()
            binding.txtBrightnessValue.text = "$value%"
        }

        // Apply config button
        binding.btnApplyConfig.setOnClickListener {
            viewModel.applyConfig()
        }
    }

    // ------------------------------------------------------------------
    // Night Mode
    // ------------------------------------------------------------------

    private fun setupNightModeSection() {
        binding.switchNightMode.setOnCheckedChangeListener(null)
        viewModel.nightMode.observe(viewLifecycleOwner) { enabled ->
            binding.switchNightMode.isChecked = enabled
        }
        binding.switchNightMode.setOnCheckedChangeListener { _, _ ->
            viewModel.toggleNightMode()
        }
    }

    // ------------------------------------------------------------------
    // Status Messages
    // ------------------------------------------------------------------

    private fun setupStatusObservers() {
        viewModel.statusMessage.observe(viewLifecycleOwner) { msg ->
            if (msg != null) {
                Snackbar.make(binding.root, msg, Snackbar.LENGTH_SHORT).show()
            }
        }
    }

    override fun onDestroyView() {
        RobotDiscovery.stopScan()
        super.onDestroyView()
        _binding = null
    }
}
