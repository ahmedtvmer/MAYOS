package com.mayos.mayos_mobile

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel

/** Connectivity is a retry hint; only an API response confirms the session. */
class ConnectivityEvents(context: Context, messenger: BinaryMessenger) {
    private val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE)
        as ConnectivityManager
    private val channel = MethodChannel(messenger, "com.mayos/connectivity")
    private val mainThread = Handler(Looper.getMainLooper())
    private val validatedNetworks = mutableSetOf<Network>()
    private var callback: ConnectivityManager.NetworkCallback? = null

    init {
        channel.setMethodCallHandler { call, result ->
            when (call.method) {
                "startListening" -> {
                    try {
                        startListening()
                        result.success(validatedNetworks.isNotEmpty())
                    } catch (_: SecurityException) {
                        result.error("connectivity_unavailable", null, null)
                    }
                }
                "stopListening" -> {
                    stopListening()
                    result.success(null)
                }
                "hasInternetConnection" -> {
                    try {
                        @Suppress("DEPRECATION")
                        val connected = manager.activeNetworkInfo?.isConnected == true
                        result.success(connected)
                    } catch (_: SecurityException) {
                        result.error("connectivity_unavailable", null, null)
                    }
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun startListening() {
        if (callback != null) return
        val listener = object : ConnectivityManager.NetworkCallback() {
            override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
                val validated = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
                } else {
                    capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                }
                publish(network, validated)
            }

            override fun onLost(network: Network) = publish(network, false)

            private fun publish(network: Network, validated: Boolean) {
                mainThread.post {
                    // A queued callback from a cancelled subscription cannot
                    // update a later subscription or a destroyed Activity.
                    if (callback !== this) return@post
                    if (validated) validatedNetworks.add(network)
                    else validatedNetworks.remove(network)
                    channel.invokeMethod("changed", validatedNetworks.isNotEmpty())
                }
            }
        }
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).build()
        manager.registerNetworkCallback(request, listener)
        callback = listener
    }

    private fun stopListening() {
        val listener = callback ?: return
        callback = null
        manager.unregisterNetworkCallback(listener)
        validatedNetworks.clear()
    }

    fun dispose() {
        stopListening()
        channel.setMethodCallHandler(null)
    }
}
