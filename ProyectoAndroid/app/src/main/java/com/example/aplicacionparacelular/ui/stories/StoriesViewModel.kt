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

    fun uploadPdf(filename: String, data: ByteArray) {
        _statusMessage.value = "Subiendo PDF..."
        RobotConnectionManager.uploadStory(filename, data) { result ->
            when (result) {
                is ApiResult.Success -> {
                    val status = result.data.optString("status")
                    if (status == "ready") {
                        val title = result.data.optString("title", filename)
                        _statusMessage.value = "Cuento listo: $title"
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
