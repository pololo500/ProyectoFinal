package com.example.aplicacionparacelular.ui.routines

import android.app.TimePickerDialog
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.aplicacionparacelular.R
import com.example.aplicacionparacelular.databinding.FragmentRoutinesBinding
import com.google.android.material.card.MaterialCardView
import com.google.android.material.snackbar.Snackbar
import com.google.android.material.switchmaterial.SwitchMaterial
import java.util.Calendar

class RoutinesFragment : Fragment() {

    private var _binding: FragmentRoutinesBinding? = null
    private val binding get() = _binding!!
    private lateinit var viewModel: RoutinesViewModel
    private lateinit var adapter: RoutineAdapter

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        viewModel = ViewModelProvider(this).get(RoutinesViewModel::class.java)
        _binding = FragmentRoutinesBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        adapter = RoutineAdapter(
            onToggle = { pos -> viewModel.toggleRoutine(pos) },
            onDelete = { pos ->
                AlertDialog.Builder(requireContext())
                    .setTitle("Eliminar rutina")
                    .setMessage("¿Estás seguro de que querés eliminar esta rutina?")
                    .setPositiveButton("Eliminar") { _, _ -> viewModel.removeRoutine(pos) }
                    .setNegativeButton("Cancelar", null)
                    .show()
            },
            onEdit = { pos -> showEditDialog(pos) }
        )

        binding.recyclerRoutines.layoutManager = LinearLayoutManager(requireContext())
        binding.recyclerRoutines.adapter = adapter

        binding.fabAddRoutine.setOnClickListener {
            showAddDialog()
        }

        viewModel.routines.observe(viewLifecycleOwner) { routines ->
            adapter.submitList(routines)
            binding.txtEmpty.visibility = if (routines.isEmpty()) View.VISIBLE else View.GONE
            binding.recyclerRoutines.visibility = if (routines.isEmpty()) View.GONE else View.VISIBLE
        }

        viewModel.syncStatus.observe(viewLifecycleOwner) { status ->
            if (status != null) {
                Snackbar.make(binding.root, status, Snackbar.LENGTH_SHORT).show()
            }
        }

        // Load routines from robot
        viewModel.loadRoutines()
    }

    private fun showAddDialog() {
        val dialogView = LayoutInflater.from(requireContext()).inflate(
            android.R.layout.simple_list_item_1, null
        )

        // Create dialog with custom layout
        val nameInput = EditText(requireContext()).apply {
            hint = "Nombre de la rutina"
            setPadding(48, 32, 48, 16)
        }
        val messageInput = EditText(requireContext()).apply {
            hint = "Mensaje del recordatorio"
            setPadding(48, 16, 48, 16)
        }
        val timeText = TextView(requireContext()).apply {
            text = "Hora: 08:00"
            setPadding(48, 16, 48, 16)
            textSize = 16f
            setOnClickListener {
                val cal = Calendar.getInstance()
                TimePickerDialog(requireContext(), { _, hour, minute ->
                    text = "Hora: ${String.format("%02d:%02d", hour, minute)}"
                    tag = String.format("%02d:%02d", hour, minute)
                }, cal.get(Calendar.HOUR_OF_DAY), cal.get(Calendar.MINUTE), true).show()
            }
        }
        timeText.tag = "08:00"

        val container = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            addView(nameInput)
            addView(timeText)
            addView(messageInput)
        }

        AlertDialog.Builder(requireContext())
            .setTitle("Nueva Rutina")
            .setView(container)
            .setPositiveButton("Agregar") { _, _ ->
                val name = nameInput.text.toString().trim()
                val time = timeText.tag?.toString() ?: "08:00"
                val message = messageInput.text.toString().trim().ifEmpty {
                    "¡Es hora de ${name.lowercase()}!"
                }
                if (name.isNotBlank()) {
                    val routine = RoutineItem(
                        id = name.lowercase().replace(" ", "_") + "_" + System.currentTimeMillis(),
                        name = name,
                        time = time,
                        reminderMessage = message,
                        transitionFrom = "",
                        transitionTo = "",
                        successMessage = "¡Muy bien! ¡Lo lograste!",
                        preReminderMinutes = 5,
                        enabled = true
                    )
                    viewModel.addRoutine(routine)
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun showEditDialog(position: Int) {
        val routine = viewModel.routines.value?.getOrNull(position) ?: return

        val nameInput = EditText(requireContext()).apply {
            hint = "Nombre"
            setText(routine.name)
            setPadding(48, 32, 48, 16)
        }
        val messageInput = EditText(requireContext()).apply {
            hint = "Mensaje del recordatorio"
            setText(routine.reminderMessage)
            setPadding(48, 16, 48, 16)
        }
        val timeText = TextView(requireContext()).apply {
            text = "Hora: ${routine.time}"
            setPadding(48, 16, 48, 16)
            textSize = 16f
            tag = routine.time
            setOnClickListener {
                val parts = routine.time.split(":")
                TimePickerDialog(requireContext(), { _, hour, minute ->
                    text = "Hora: ${String.format("%02d:%02d", hour, minute)}"
                    tag = String.format("%02d:%02d", hour, minute)
                }, parts.getOrNull(0)?.toIntOrNull() ?: 8,
                    parts.getOrNull(1)?.toIntOrNull() ?: 0, true).show()
            }
        }

        val container = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            addView(nameInput)
            addView(timeText)
            addView(messageInput)
        }

        AlertDialog.Builder(requireContext())
            .setTitle("Editar Rutina")
            .setView(container)
            .setPositiveButton("Guardar") { _, _ ->
                val updated = routine.copy(
                    name = nameInput.text.toString().trim().ifEmpty { routine.name },
                    time = timeText.tag?.toString() ?: routine.time,
                    reminderMessage = messageInput.text.toString().trim().ifEmpty { routine.reminderMessage }
                )
                viewModel.updateRoutine(position, updated)
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

/**
 * RecyclerView Adapter for routine items.
 */
class RoutineAdapter(
    private val onToggle: (Int) -> Unit,
    private val onDelete: (Int) -> Unit,
    private val onEdit: (Int) -> Unit
) : RecyclerView.Adapter<RoutineAdapter.ViewHolder>() {

    private var items: List<RoutineItem> = emptyList()

    fun submitList(newItems: List<RoutineItem>) {
        items = newItems
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val card = MaterialCardView(parent.context).apply {
            layoutParams = RecyclerView.LayoutParams(
                RecyclerView.LayoutParams.MATCH_PARENT,
                RecyclerView.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = 12 }
            radius = 16f * resources.displayMetrics.density
            cardElevation = 2f * resources.displayMetrics.density
            setContentPadding(
                (16 * resources.displayMetrics.density).toInt(),
                (12 * resources.displayMetrics.density).toInt(),
                (16 * resources.displayMetrics.density).toInt(),
                (12 * resources.displayMetrics.density).toInt()
            )
        }

        val layout = LinearLayout(parent.context).apply {
            orientation = LinearLayout.VERTICAL
        }

        val topRow = LinearLayout(parent.context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER_VERTICAL
        }

        val dp = parent.context.resources.displayMetrics.density

        val timeText = TextView(parent.context).apply {
            textSize = 24f
            setPadding(0, 0, (12 * dp).toInt(), 0)
            setTextColor(parent.context.getColor(R.color.primary))
        }

        val nameText = TextView(parent.context).apply {
            textSize = 16f
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }

        val enableSwitch = SwitchMaterial(parent.context)

        topRow.addView(timeText)
        topRow.addView(nameText)
        topRow.addView(enableSwitch)

        val messageText = TextView(parent.context).apply {
            textSize = 13f
            setTextColor(parent.context.getColor(R.color.text_hint))
            setPadding(0, (4 * dp).toInt(), 0, 0)
        }

        val statusText = TextView(parent.context).apply {
            textSize = 12f
            setPadding(0, (4 * dp).toInt(), 0, 0)
        }

        layout.addView(topRow)
        layout.addView(messageText)
        layout.addView(statusText)
        card.addView(layout)

        return ViewHolder(card, timeText, nameText, messageText, statusText, enableSwitch)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val item = items[position]
        holder.timeText.text = item.time
        holder.nameText.text = item.name
        holder.messageText.text = "\"${item.reminderMessage}\""
        holder.enableSwitch.isChecked = item.enabled

        // Status
        holder.statusText.text = when {
            item.completed -> "✅ Completada"
            item.reminded -> "🔔 Recordada"
            else -> ""
        }
        holder.statusText.visibility = if (item.reminded || item.completed) View.VISIBLE else View.GONE

        holder.enableSwitch.setOnCheckedChangeListener(null)
        holder.enableSwitch.isChecked = item.enabled
        holder.enableSwitch.setOnCheckedChangeListener { _, _ ->
            onToggle(holder.bindingAdapterPosition)
        }

        holder.itemView.setOnClickListener { onEdit(holder.bindingAdapterPosition) }
        holder.itemView.setOnLongClickListener {
            onDelete(holder.bindingAdapterPosition)
            true
        }
    }

    override fun getItemCount(): Int = items.size

    class ViewHolder(
        view: View,
        val timeText: TextView,
        val nameText: TextView,
        val messageText: TextView,
        val statusText: TextView,
        val enableSwitch: SwitchMaterial
    ) : RecyclerView.ViewHolder(view)
}
