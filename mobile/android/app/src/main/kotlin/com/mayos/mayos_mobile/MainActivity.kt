package com.mayos.mayos_mobile

import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    private val shareExecutor = Executors.newSingleThreadExecutor()
    private var shareChannel: MethodChannel? = null
    private var shareReceiverReady = false
    private var initialShare: Map<String, Any?>? = null
    private var initialShareResolved = false
    private val initialShareWaiters = mutableListOf<MethodChannel.Result>()

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        shareChannel = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "com.mayos/share"
        )
        shareChannel?.setMethodCallHandler { call, result ->
            when (call.method) {
                "getInitialIntent" -> {
                    if (initialShareResolved) {
                        result.success(initialShare)
                        initialShare = null
                    } else {
                        initialShareWaiters.add(result)
                    }
                }
                "startListening" -> {
                    shareReceiverReady = true
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
        processShareIntent(intent, initial = true)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.flags and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY != 0) {
            setIntent(Intent())
            return
        }
        if (intent.action == Intent.ACTION_SEND &&
            intent.type == "text/plain"
        ) {
            setIntent(Intent())
        } else {
            setIntent(intent)
            return
        }
        processShareIntent(intent, initial = false)
    }

    override fun onDestroy() {
        shareExecutor.shutdownNow()
        super.onDestroy()
    }

    private fun processShareIntent(source: Intent?, initial: Boolean) {
        if (source != null &&
            source.flags and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY != 0
        ) {
            if (initial) {
                setIntent(Intent())
                initialShareResolved = true
            }
            return
        }
        if (source?.action != Intent.ACTION_SEND ||
            source.type != "text/plain"
        ) {
            if (initial) initialShareResolved = true
            return
        }
        if (initial) setIntent(Intent())
        shareExecutor.execute {
            val payload = sharePayload(source)
            runOnUiThread {
                if (initial) {
                    initialShare = payload
                    initialShareResolved = true
                    initialShareWaiters.forEach { it.success(initialShare) }
                    initialShareWaiters.clear()
                } else if (shareReceiverReady && payload != null) {
                    shareChannel?.invokeMethod("sharedText", payload)
                } else if (payload != null) {
                    initialShare = payload
                }
            }
        }
    }

    private fun sharePayload(source: Intent): Map<String, Any?>? {
        val uri: Uri? = source.getParcelableExtra(Intent.EXTRA_STREAM)
        if (uri != null) {
            // If both caption and file are present, import the file content.
            return readTextFile(uri)
        }
        val text = source.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
        return text?.let { mapOf("text" to it) }
    }

    private fun readTextFile(uri: Uri): Map<String, Any?> {
        val name = try {
            contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (cursor.moveToFirst() && index >= 0) {
                    cursor.getString(index)
                } else {
                    null
                }
            }
        } catch (_: Exception) {
            return mapOf("error" to "file_read_failed")
        }
        val fileName = name ?: uri.lastPathSegment.orEmpty()
        if (!fileName.endsWith(".txt", ignoreCase = true)) {
            return mapOf("error" to "not_txt")
        }
        val bytes = try {
            contentResolver.openInputStream(uri)?.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                var total = 0
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    total += count
                    if (total > MAX_FILE_BYTES) {
                        return mapOf("error" to "file_too_large")
                    }
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            }
        } catch (_: Exception) {
            return mapOf("error" to "file_read_failed")
        } ?: return mapOf("error" to "file_read_failed")
        return try {
            val decoder = StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
            mapOf("text" to decoder.decode(ByteBuffer.wrap(bytes)).toString())
        } catch (_: Exception) {
            mapOf("error" to "invalid_utf8")
        }
    }

    companion object {
        private const val MAX_FILE_BYTES = 1024 * 1024
    }
}
