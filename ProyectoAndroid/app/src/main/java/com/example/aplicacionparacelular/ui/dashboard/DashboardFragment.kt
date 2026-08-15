package com.example.aplicacionparacelular.ui.dashboard

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import com.example.aplicacionparacelular.R
import com.example.aplicacionparacelular.databinding.FragmentDashboardBinding
import com.example.aplicacionparacelular.network.RobotConnectionManager
import com.google.android.material.snackbar.Snackbar

class DashboardFragment : Fragment() {

    private var _binding: FragmentDashboardBinding? = null
    private val binding get() = _binding!!
    private lateinit var viewModel: DashboardViewModel

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        viewModel = ViewModelProvider(this).get(DashboardViewModel::class.java)
        _binding = FragmentDashboardBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Observe connection status
        RobotConnectionManager.isConnected.observe(viewLifecycleOwner) { connected ->
            if (connected) {
                binding.chipConnectionStatus.text = getString(R.string.dashboard_connection_status_online)
                binding.chipConnectionStatus.setChipBackgroundColorResource(R.color.card_connection_online)
            } else {
                binding.chipConnectionStatus.text = getString(R.string.dashboard_connection_status_offline)
                binding.chipConnectionStatus.setChipBackgroundColorResource(R.color.card_connection_offline)
            }
        }

        // Observe robot status for power state
        RobotConnectionManager.robotStatus.observe(viewLifecycleOwner) { status ->
            if (status != null) {
                val powerOn = status.optBoolean("power_on", true)
                val nightMode = status.optBoolean("night_mode", false)
                updatePowerUI(powerOn, nightMode)
            }
        }

        // Observe ViewModel data
        viewModel.totalInteractions.observe(viewLifecycleOwner) { value ->
            binding.txtInteractionsValue.text = value
        }

        viewModel.playtimeMinutes.observe(viewLifecycleOwner) { value ->
            binding.txtPlaytimeValue.text = value
        }

        viewModel.moodLabel.observe(viewLifecycleOwner) { value ->
            binding.txtMoodValue.text = value
        }

        viewModel.alertMessages.observe(viewLifecycleOwner) { alerts ->
            updateAlerts(alerts)
        }

        // Celebrate button
        binding.cardCelebrate.setOnClickListener {
            RobotConnectionManager.celebrate { result ->
                val msg = when (result) {
                    is com.example.aplicacionparacelular.network.ApiResult.Success ->
                        "🎉 ¡Celebración enviada al peluche!"
                    is com.example.aplicacionparacelular.network.ApiResult.Error ->
                        "No se pudo enviar. ¿Está conectado el peluche?"
                }
                view.let { v ->
                    Snackbar.make(v, msg, Snackbar.LENGTH_SHORT).show()
                }
            }
        }

        // Power toggle button
        binding.btnPowerToggle.setOnClickListener {
            viewModel.togglePower()
        }

        // Initial data load
        viewModel.refreshTelemetry()
    }

    override fun onResume() {
        super.onResume()
        viewModel.refreshTelemetry()
    }

    private fun updatePowerUI(powerOn: Boolean, nightMode: Boolean) {
        if (nightMode) {
            binding.btnPowerToggle.text = "🌙 Modo Noche"
        } else if (powerOn) {
            binding.btnPowerToggle.text = "⏻ Encendido"
        } else {
            binding.btnPowerToggle.text = "⏻ Apagado"
        }
    }

    private fun updateAlerts(alerts: List<String>) {
        val container = binding.alertsContainer
        container.removeAllViews()

        if (alerts.isEmpty()) {
            val tv = TextView(requireContext()).apply {
                text = getString(R.string.dashboard_no_alerts)
                setPadding(32, 24, 32, 24)
                setTextColor(resources.getColor(R.color.text_hint, null))
            }
            container.addView(tv)
        } else {
            for (alert in alerts) {
                val tv = TextView(requireContext()).apply {
                    text = alert
                    setPadding(32, 16, 32, 16)
                    textSize = 14f
                }
                container.addView(tv)
            }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
