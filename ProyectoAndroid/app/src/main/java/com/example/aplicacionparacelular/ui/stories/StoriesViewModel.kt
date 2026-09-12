package com.example.aplicacionparacelular.ui.stories

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import com.example.aplicacionparacelular.network.ApiResult
import com.example.aplicacionparacelular.network.RobotConnectionManager

data class StoryItem(
    val id: String,
    val title: String,
    val wordCount: Int,
)

data class SongItem(
    val filename: String,
    val sizeBytes: Long,
    val modified: String,
)

class StoriesViewModel : ViewModel() {

    private val _stories = MutableLiveData<List<StoryItem>>(emptyList())
    val stories: LiveData<List<StoryItem>> = _stories

    private val _statusMessage = MutableLiveData<String?>()
    val statusMessage: LiveData<String?> = _statusMessage

    private val _storyToEdit = MutableLiveData<StoryDetail?>()
    val storyToEdit: LiveData<StoryDetail?> = _storyToEdit

    private val _saveInProgress = MutableLiveData(false)
    val saveInProgress: LiveData<Boolean> = _saveInProgress

    fun loadStories() {
        RobotConnectionManager.fetchStories { result ->
            when (result) {
                is ApiResult.Success -> {
                    val arr = result.data.optJSONArray("stories")
                    val list = mutableListOf<StoryItem>()
                    if (arr != null) {
                        for (i in 0 until arr.length()) {
                            val obj = arr.optJSONObject(i) ?: continue
                            list.add(
                                StoryItem(
                                    id = obj.optString("id", ""),
                                    title = obj.optString("title", ""),
                                    wordCount = obj.optInt("word_count", 0),
                                )
                            )
                        }
                    }
                    _stories.value = list
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error al cargar cuentos: ${result.message}"
                }
            }
        }
    }

    fun uploadPdf(filename: String, data: ByteArray, title: String? = null) {
        _statusMessage.value = "Subiendo PDF..."
        val headerTitle = title?.trim()?.ifBlank { null }?.take(StoryJson.TITLE_MAX_LEN)
        RobotConnectionManager.uploadStory(filename, data, headerTitle) { result ->
            when (result) {
                is ApiResult.Success -> {
                    val status = result.data.optString("status")
                    if (status == "ready") {
                        val readyTitle = result.data.optString("title", filename)
                        _statusMessage.value = "Cuento listo: $readyTitle"
                        loadStories()
                    } else {
                        val reason = result.data.optString("reason", "No se pudo publicar")
                        _statusMessage.value = reason
                    }
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error: ${result.message}"
                }
            }
        }
    }

    fun loadStory(id: String) {
        _statusMessage.value = "Cargando cuento..."
        RobotConnectionManager.fetchStory(id) { result ->
            when (result) {
                is ApiResult.Success -> {
                    _storyToEdit.value = StoryJson.parseDetail(result.data)
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error: ${result.message}"
                }
            }
        }
    }

    fun saveStory(id: String, title: String, text: String) {
        val trimmedTitle = title.trim().take(StoryJson.TITLE_MAX_LEN)
        if (trimmedTitle.isEmpty()) {
            _statusMessage.value = "El nombre no puede estar vacío"
            return
        }
        _saveInProgress.value = true
        RobotConnectionManager.updateStory(id, trimmedTitle, text) { result ->
            _saveInProgress.value = false
            when (result) {
                is ApiResult.Success -> {
                    val update = StoryJson.parseUpdateStatus(result.data)
                    if (update.status == "rejected") {
                        _statusMessage.value = update.reason ?: "No se pudo guardar"
                    } else {
                        _statusMessage.value = "Cuento actualizado"
                        _storyToEdit.value = null
                        loadStories()
                    }
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error: ${result.message}"
                }
            }
        }
    }

    fun clearStoryToEdit() {
        _storyToEdit.value = null
    }

    fun deleteStory(id: String) {
        RobotConnectionManager.deleteStory(id) { result ->
            when (result) {
                is ApiResult.Success -> {
                    _statusMessage.value = "Cuento eliminado"
                    loadStories()
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error: ${result.message}"
                }
            }
        }
    }

    private val _songs = MutableLiveData<List<SongItem>>(emptyList())
    val songs: LiveData<List<SongItem>> = _songs

    private val _currentlyPlaying = MutableLiveData<String?>(null)
    val currentlyPlaying: LiveData<String?> = _currentlyPlaying

    fun loadSongs() {
        RobotConnectionManager.fetchMusic { result ->
            when (result) {
                is ApiResult.Success -> {
                    val songsArray = result.data.optJSONArray("songs")
                    val list = mutableListOf<SongItem>()
                    if (songsArray != null) {
                        for (i in 0 until songsArray.length()) {
                            val obj = songsArray.optJSONObject(i) ?: continue
                            list.add(
                                SongItem(
                                    filename = obj.optString("filename", ""),
                                    sizeBytes = obj.optLong("size_bytes", 0),
                                    modified = obj.optString("modified", ""),
                                )
                            )
                        }
                    }
                    _songs.value = list
                    val playing = if (result.data.isNull("currently_playing")) null
                    else result.data.optString("currently_playing", null)?.ifBlank { null }
                    _currentlyPlaying.value = playing
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error al cargar canciones: ${result.message}"
                }
            }
        }
    }

    fun deleteSong(filename: String) {
        RobotConnectionManager.deleteMusic(filename) { result ->
            when (result) {
                is ApiResult.Success -> {
                    _statusMessage.value = "Canción eliminada"
                    loadSongs()
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error: ${result.message}"
                }
            }
        }
    }

    fun uploadSong(filename: String, data: ByteArray) {
        _statusMessage.value = "Subiendo canción..."
        RobotConnectionManager.uploadMusic(filename, data) { result ->
            when (result) {
                is ApiResult.Success -> {
                    _statusMessage.value = "Canción subida correctamente"
                    loadSongs()
                }
                is ApiResult.Error -> {
                    _statusMessage.value = "Error: ${result.message}"
                }
            }
        }
    }

    fun playSong(filename: String) {
        _currentlyPlaying.value = filename
        RobotConnectionManager.playMusic(filename) { result ->
            when (result) {
                is ApiResult.Success -> loadSongs()
                is ApiResult.Error -> {
                    _currentlyPlaying.value = null
                    _statusMessage.value = "Error al reproducir: ${result.message}"
                }
            }
        }
    }

    fun stopMusic() {
        _currentlyPlaying.value = null
        RobotConnectionManager.stopMusic { result ->
            when (result) {
                is ApiResult.Success -> loadSongs()
                is ApiResult.Error -> {
                    _statusMessage.value = "Error al detener: ${result.message}"
                    loadSongs()
                }
            }
        }
    }
}
