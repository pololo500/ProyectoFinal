package com.example.aplicacionparacelular.ui.stories

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import com.example.aplicacionparacelular.network.ApiResult
import com.example.aplicacionparacelular.network.RobotConnectionManager
import org.json.JSONObject

data class StoryItem(
    val id: String,
    val title: String,
    val wordCount: Int,
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
                    if (arr != None) {
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
}
