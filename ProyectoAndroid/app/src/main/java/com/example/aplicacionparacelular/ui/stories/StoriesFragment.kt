package com.example.aplicacionparacelular.ui.stories

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import com.example.aplicacionparacelular.R
import com.example.aplicacionparacelular.databinding.FragmentStoriesBinding
import com.example.aplicacionparacelular.network.RobotApiClient
import com.google.android.material.button.MaterialButton
import com.google.android.material.snackbar.Snackbar

class StoriesFragment : Fragment() {

    private var _binding: FragmentStoriesBinding? = null
    private val binding get() = _binding!!
    private lateinit var viewModel: StoriesViewModel

    private val pdfPicker = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val uri = result.data?.data ?: return@registerForActivityResult
        val context = requireContext()
        val filename = fileNameFromUri(context, uri, "cuento.pdf", ".pdf")
        try {
            val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                ?: return@registerForActivityResult
            viewModel.uploadPdf(filename, bytes)
        } catch (exc: Exception) {
            Snackbar.make(binding.root, "No pude leer el PDF: ${exc.message}", Snackbar.LENGTH_SHORT).show()
        }
    }

    private val audioPicker = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
        val uri = result.data?.data ?: return@registerForActivityResult
        val context = requireContext()
        val filename = fileNameFromUri(context, uri, "cancion.mp3", null)
        try {
            val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                ?: return@registerForActivityResult
            viewModel.uploadSong(filename, bytes)
        } catch (exc: Exception) {
            Snackbar.make(binding.root, "Error al leer archivo: ${exc.message}", Snackbar.LENGTH_SHORT).show()
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View {
        viewModel = ViewModelProvider(this).get(StoriesViewModel::class.java)
        _binding = FragmentStoriesBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        binding.btnUploadPdf.setOnClickListener {
            val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                type = "application/pdf"
                addCategory(Intent.CATEGORY_OPENABLE)
            }
            pdfPicker.launch(intent)
        }
        binding.btnUploadSong.setOnClickListener {
            val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                type = "audio/*"
                addCategory(Intent.CATEGORY_OPENABLE)
            }
            audioPicker.launch(intent)
        }
        binding.btnStopSong.setOnClickListener { viewModel.stopMusic() }

        viewModel.stories.observe(viewLifecycleOwner) { rebuildStories(it) }
        viewModel.songs.observe(viewLifecycleOwner) { rebuildSongs() }
        viewModel.currentlyPlaying.observe(viewLifecycleOwner) { rebuildSongs() }
        viewModel.statusMessage.observe(viewLifecycleOwner) { msg ->
            if (!msg.isNullOrBlank()) {
                Snackbar.make(binding.root, msg, Snackbar.LENGTH_LONG).show()
            }
        }
        if (RobotApiClient.isConfigured()) {
            viewModel.loadStories()
            viewModel.loadSongs()
        }
    }

    override fun onResume() {
        super.onResume()
        if (RobotApiClient.isConfigured()) {
            viewModel.loadSongs()
        }
    }

    private fun rebuildStories(stories: List<StoryItem>) {
        binding.storiesContainer.removeAllViews()
        if (stories.isEmpty()) {
            val empty = TextView(requireContext()).apply {
                text = getString(R.string.stories_empty)
                setPadding(0, 24, 0, 24)
                setTextColor(resources.getColor(R.color.text_hint, null))
            }
            binding.storiesContainer.addView(empty)
            return
        }
        for (story in stories) {
            val row = LinearLayout(requireContext()).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = android.view.Gravity.CENTER_VERTICAL
                setPadding(0, 8, 0, 8)
            }
            val label = TextView(requireContext()).apply {
                text = "${story.title}  (${story.wordCount} palabras)"
                textSize = 14f
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            val deleteBtn = MaterialButton(
                requireContext(),
                null,
                com.google.android.material.R.attr.materialButtonOutlinedStyle,
            ).apply {
                text = "Borrar"
                textSize = 12f
                minHeight = 48
                setOnClickListener {
                    AlertDialog.Builder(requireContext())
                        .setTitle(story.title)
                        .setMessage(getString(R.string.stories_delete_confirm))
                        .setPositiveButton(android.R.string.ok) { _, _ -> viewModel.deleteStory(story.id) }
                        .setNegativeButton(android.R.string.cancel, null)
                        .show()
                }
            }
            row.addView(label)
            row.addView(deleteBtn)
            binding.storiesContainer.addView(row)
        }
    }

    private fun rebuildSongs() {
        val songs = viewModel.songs.value ?: emptyList()
        val currentlyPlaying = viewModel.currentlyPlaying.value
        binding.songsContainer.removeAllViews()
        if (songs.isEmpty()) {
            val tv = TextView(requireContext()).apply {
                text = getString(R.string.files_songs_empty)
                setPadding(0, 16, 0, 16)
                setTextColor(resources.getColor(R.color.text_hint, null))
            }
            binding.songsContainer.addView(tv)
            return
        }
        for (song in songs) {
            val isPlaying = song.filename == currentlyPlaying
            val row = LinearLayout(requireContext()).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = android.view.Gravity.CENTER_VERTICAL
                setPadding(0, 8, 0, 8)
            }
            val nameText = TextView(requireContext()).apply {
                text = song.filename
                textSize = 14f
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            row.addView(nameText)
            if (isPlaying) {
                val stopBtn = MaterialButton(
                    requireContext(),
                    null,
                    com.google.android.material.R.attr.materialButtonOutlinedStyle,
                ).apply {
                    text = "Stop"
                    textSize = 12f
                    minHeight = 48
                    contentDescription = getString(R.string.dashboard_music_stop)
                    setOnClickListener { viewModel.stopMusic() }
                }
                row.addView(stopBtn)
            } else {
                val playBtn = MaterialButton(
                    requireContext(),
                    null,
                    com.google.android.material.R.attr.materialButtonOutlinedStyle,
                ).apply {
                    text = "Play"
                    textSize = 12f
                    minHeight = 48
                    contentDescription = getString(R.string.dashboard_music_play)
                    setOnClickListener { viewModel.playSong(song.filename) }
                }
                row.addView(playBtn)
            }
            val deleteBtn = MaterialButton(
                requireContext(),
                null,
                com.google.android.material.R.attr.materialButtonOutlinedStyle,
            ).apply {
                text = "Borrar"
                textSize = 12f
                minHeight = 48
                setOnClickListener {
                    AlertDialog.Builder(requireContext())
                        .setTitle(getString(R.string.files_songs_delete_title))
                        .setMessage("¿Eliminar '${song.filename}'?")
                        .setPositiveButton("Eliminar") { _, _ -> viewModel.deleteSong(song.filename) }
                        .setNegativeButton("Cancelar", null)
                        .show()
                }
            }
            row.addView(deleteBtn)
            binding.songsContainer.addView(row)
        }
    }

    private fun fileNameFromUri(
        context: Context,
        uri: android.net.Uri,
        fallback: String,
        forceSuffix: String?,
    ): String {
        var name: String? = null
        if (uri.scheme == "content") {
            try {
                context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                    if (cursor.moveToFirst()) {
                        val idx = cursor.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                        if (idx != -1) name = cursor.getString(idx)
                    }
                }
            } catch (_: Exception) {
            }
        }
        if (name == null) {
            name = uri.lastPathSegment?.substringAfterLast("/")
        }
        val safe = name?.trim() ?: fallback
        if (forceSuffix != null) {
            return if (safe.lowercase().endsWith(forceSuffix)) safe else "$safe$forceSuffix"
        }
        return if (!safe.contains(".")) "$safe.mp3" else safe
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
