package com.example.aplicacionparacelular.network

internal object UrlEncoding {
    fun headerValue(raw: String): String =
        java.net.URLEncoder.encode(raw, "UTF-8").replace("+", "%20")
}
