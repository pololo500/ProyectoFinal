package com.example.aplicacionparacelular.ui.stories

import com.example.aplicacionparacelular.network.UrlEncoding
import org.json.JSONObject

data class StoryDetail(
    val id: String,
    val title: String,
    val wordCount: Int,
    val createdAt: String,
    val text: String,
)

data class StoryUpdateStatus(
    val status: String,
    val reason: String?,
)

object StoryJson {
    const val TITLE_MAX_LEN = 80

    fun parseDetail(json: JSONObject): StoryDetail = StoryDetail(
        id = json.optString("id", ""),
        title = json.optString("title", ""),
        wordCount = json.optInt("word_count", 0),
        createdAt = json.optString("created_at", ""),
        text = json.optString("text", ""),
    )

    fun parseUpdateStatus(json: JSONObject): StoryUpdateStatus {
        val status = json.optString("status", "")
        val reason = json.optString("reason", "").ifBlank { null }
        return StoryUpdateStatus(status, reason)
    }

    fun pdfStem(filename: String): String {
        val base = filename.substringAfterLast('/').substringAfterLast('\\')
        return if (base.endsWith(".pdf", ignoreCase = true) && base.length > 4) {
            base.substring(0, base.length - 4)
        } else {
            base
        }
    }

    fun encodeHeaderValue(value: String): String = UrlEncoding.headerValue(value)
}
