package com.example.aplicacionparacelular.ui.medical

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import com.example.aplicacionparacelular.R
import com.example.aplicacionparacelular.databinding.FragmentMedicalBinding
import com.google.android.material.card.MaterialCardView
import java.util.Calendar

class MedicalFragment : Fragment() {

    private var _binding: FragmentMedicalBinding? = null
    private val binding get() = _binding!!
    private lateinit var viewModel: MedicalViewModel

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        viewModel = ViewModelProvider(this).get(MedicalViewModel::class.java)
        _binding = FragmentMedicalBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Observe appointments
        viewModel.appointments.observe(viewLifecycleOwner) { appointments ->
            binding.appointmentsContainer.removeAllViews()
            if (appointments.isEmpty()) {
                val tv = TextView(requireContext()).apply {
                    text = getString(R.string.medical_no_appointments)
                    setPadding(0, 24, 0, 24)
                    setTextColor(resources.getColor(R.color.text_hint, null))
                }
                binding.appointmentsContainer.addView(tv)
            } else {
                appointments.forEachIndexed { index, appt ->
                    val card = createAppointmentCard(appt, index)
                    binding.appointmentsContainer.addView(card)
                }
            }
        }

        // Observe vaccines
        viewModel.vaccines.observe(viewLifecycleOwner) { vaccines ->
            binding.vaccinesContainer.removeAllViews()
            vaccines.forEachIndexed { index, vaccine ->
                val row = createVaccineRow(vaccine, index)
                binding.vaccinesContainer.addView(row)
            }
        }

        // Add appointment button
        binding.btnAddAppointment.setOnClickListener {
            showAddAppointmentDialog()
        }

        // Load data
        viewModel.loadData(requireContext())
    }

    private fun createAppointmentCard(appointment: Appointment, position: Int): View {
        val dp = resources.displayMetrics.density

        val card = MaterialCardView(requireContext()).apply {
            radius = 12 * dp
            cardElevation = 2 * dp
            setContentPadding(
                (16 * dp).toInt(), (12 * dp).toInt(),
                (16 * dp).toInt(), (12 * dp).toInt()
            )
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = (8 * dp).toInt() }
        }

        val layout = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER_VERTICAL
        }

        val textLayout = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }

        textLayout.addView(TextView(requireContext()).apply {
            text = "📅 ${appointment.title}"
            textSize = 15f
            setTextColor(resources.getColor(R.color.on_background_light, null))
        })

        textLayout.addView(TextView(requireContext()).apply {
            text = appointment.date
            textSize = 13f
            setTextColor(resources.getColor(R.color.text_hint, null))
        })

        if (appointment.notes.isNotBlank()) {
            textLayout.addView(TextView(requireContext()).apply {
                text = appointment.notes
                textSize = 12f
                setTextColor(resources.getColor(R.color.text_hint, null))
                setPadding(0, (4 * dp).toInt(), 0, 0)
            })
        }

        val deleteBtn = com.google.android.material.button.MaterialButton(
            requireContext(), null,
            com.google.android.material.R.attr.materialButtonOutlinedStyle
        ).apply {
            text = "✕"
            textSize = 14f
            minimumWidth = 0
            minimumHeight = 0
            setPadding((8 * dp).toInt(), 0, (8 * dp).toInt(), 0)
            setOnClickListener {
                AlertDialog.Builder(requireContext())
                    .setTitle("Eliminar turno")
                    .setMessage("¿Eliminar '${appointment.title}'?")
                    .setPositiveButton("Eliminar") { _, _ ->
                        viewModel.removeAppointment(requireContext(), position)
                    }
                    .setNegativeButton("Cancelar", null)
                    .show()
            }
        }

        layout.addView(textLayout)
        layout.addView(deleteBtn)
        card.addView(layout)
        return card
    }

    private fun createVaccineRow(vaccine: Vaccine, position: Int): View {
        val dp = resources.displayMetrics.density

        val row = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER_VERTICAL
            setPadding(0, (6 * dp).toInt(), 0, (6 * dp).toInt())
        }

        val checkbox = CheckBox(requireContext()).apply {
            isChecked = vaccine.applied
            setOnCheckedChangeListener { _, _ ->
                viewModel.toggleVaccine(requireContext(), position)
            }
        }

        val nameText = TextView(requireContext()).apply {
            text = vaccine.name
            textSize = 14f
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            setPadding((8 * dp).toInt(), 0, 0, 0)
            if (vaccine.applied) {
                paintFlags = paintFlags or android.graphics.Paint.STRIKE_THRU_TEXT_FLAG
                setTextColor(resources.getColor(R.color.text_hint, null))
            }
        }

        val ageText = TextView(requireContext()).apply {
            text = if (vaccine.applied) "${vaccine.scheduledAge} ✓" else vaccine.scheduledAge
            textSize = 12f
            setTextColor(
                if (vaccine.applied) resources.getColor(R.color.card_connection_online, null)
                else resources.getColor(R.color.text_hint, null)
            )
        }

        row.addView(checkbox)
        row.addView(nameText)
        row.addView(ageText)
        return row
    }

    private fun showAddAppointmentDialog() {
        val titleInput = EditText(requireContext()).apply {
            hint = "Título (ej. Control pediátrico)"
            setPadding(48, 32, 48, 16)
        }
        val dateText = TextView(requireContext()).apply {
            text = "Seleccionar fecha y hora"
            setPadding(48, 16, 48, 16)
            textSize = 16f
            setTextColor(resources.getColor(R.color.primary, null))
            setOnClickListener {
                val cal = Calendar.getInstance()
                DatePickerDialog(requireContext(), { _, year, month, day ->
                    TimePickerDialog(requireContext(), { _, hour, minute ->
                        val dateStr = "${day}/${month + 1}/$year ${String.format("%02d:%02d", hour, minute)}"
                        text = dateStr
                        tag = dateStr
                    }, cal.get(Calendar.HOUR_OF_DAY), cal.get(Calendar.MINUTE), true).show()
                }, cal.get(Calendar.YEAR), cal.get(Calendar.MONTH), cal.get(Calendar.DAY_OF_MONTH)).show()
            }
        }
        val notesInput = EditText(requireContext()).apply {
            hint = "Notas (opcional)"
            setPadding(48, 16, 48, 16)
        }

        val container = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.VERTICAL
            addView(titleInput)
            addView(dateText)
            addView(notesInput)
        }

        AlertDialog.Builder(requireContext())
            .setTitle("Nuevo Turno Médico")
            .setView(container)
            .setPositiveButton("Agregar") { _, _ ->
                val title = titleInput.text.toString().trim()
                val date = dateText.tag?.toString() ?: ""
                val notes = notesInput.text.toString().trim()
                if (title.isNotBlank() && date.isNotBlank()) {
                    val appointment = Appointment(
                        id = "appt_${System.currentTimeMillis()}",
                        title = title,
                        date = date,
                        notes = notes
                    )
                    viewModel.addAppointment(requireContext(), appointment)
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
