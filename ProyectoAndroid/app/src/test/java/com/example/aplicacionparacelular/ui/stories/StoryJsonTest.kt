package com.example.aplicacionparacelular.ui.stories

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class StoryJsonTest {

    @Test
    fun parseDetail_readsContractFields() {
        val json = JSONObject(
            """
            {
              "id": "el-bosque-a1b2c3",
              "title": "El bosque",
              "word_count": 123,
              "created_at": "2026-09-08T12:00:00",
              "text": "Había una vez un bosque."
            }
            """.trimIndent(),
        )
        val detail = StoryJson.parseDetail(json)
        assertEquals("el-bosque-a1b2c3", detail.id)
        assertEquals("El bosque", detail.title)
        assertEquals(123, detail.wordCount)
        assertEquals("2026-09-08T12:00:00", detail.createdAt)
        assertEquals("Había una vez un bosque.", detail.text)
    }

    @Test
    fun parseUpdateStatus_okAndRejected() {
        val ok = StoryJson.parseUpdateStatus(JSONObject("""{"status":"ok","id":"x","title":"T","word_count":4}"""))
        assertEquals("ok", ok.status)
        assertNull(ok.reason)

        val rejected = StoryJson.parseUpdateStatus(
            JSONObject("""{"status":"rejected","reason":"No parece un cuento infantil"}"""),
        )
        assertEquals("rejected", rejected.status)
        assertEquals("No parece un cuento infantil", rejected.reason)
    }

    @Test
    fun pdfStem_stripsPdfExtensionOnly() {
        assertEquals("El bosque", StoryJson.pdfStem("El bosque.pdf"))
        assertEquals("El bosque", StoryJson.pdfStem("El bosque.PDF"))
        assertEquals("mi.cuento", StoryJson.pdfStem("carpeta/mi.cuento.pdf"))
        assertEquals("sin-ext", StoryJson.pdfStem("sin-ext"))
    }

    @Test
    fun encodeHeaderValue_spacesAsPercent20() {
        assertEquals("El%20bosque", StoryJson.encodeHeaderValue("El bosque"))
        assertEquals("Ni%C3%B1o", StoryJson.encodeHeaderValue("Niño"))
    }
}
