package com.msmp.bridge;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.logging.Level;

/**
 * HTTP client for communicating with the MSMP website API
 */
public class APIClient {

    private final MSMPBridge plugin;
    private final String baseUrl;
    private final String apiKey;
    private static final int CONNECT_TIMEOUT = 5000;
    private static final int READ_TIMEOUT = 10000;

    public APIClient(MSMPBridge plugin, String baseUrl, String apiKey) {
        this.plugin = plugin;
        // Remove trailing slash
        this.baseUrl = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        this.apiKey = apiKey;
    }

    /**
     * Test connection to the website API
     */
    public boolean testConnection() {
        try {
            String response = get("/api/plugin/ping?apiKey=" + urlEncode(apiKey));
            return response != null;
        } catch (Exception e) {
            if (plugin.getConfig().getBoolean("debug", false)) {
                plugin.getLogger().log(Level.INFO, "Connection test failed: " + e.getMessage());
            }
            return false;
        }
    }

    /**
     * Send server heartbeat with status data
     */
    public boolean sendHeartbeat(double[] tps, String playersJson, int maxPlayers) {
        try {
            String tps1m = String.format("%.1f", tps[0]);
            String tps5m = tps.length > 1 ? String.format("%.1f", tps[1]) : tps1m;
            String tps15m = tps.length > 2 ? String.format("%.1f", tps[2]) : tps1m;

            String json = "{\"apiKey\":\"" + escapeJson(apiKey) + "\","
                    + "\"tps\":[" + tps1m + "," + tps5m + "," + tps15m + "],"
                    + "\"onlinePlayers\":" + playersJson + ","
                    + "\"maxPlayers\":" + maxPlayers + ","
                    + "\"serverVersion\":\"" + escapeJson(plugin.getServer().getVersion()) + "\","
                    + "\"online\":true}";

            String response = post("/api/plugin/heartbeat", json);
            return response != null;
        } catch (Exception e) {
            if (plugin.getConfig().getBoolean("debug", false)) {
                plugin.getLogger().log(Level.WARNING, "Heartbeat failed: " + e.getMessage());
            }
            return false;
        }
    }

    /**
     * Send server offline notification
     */
    public void sendServerOffline() {
        try {
            String json = "{\"apiKey\":\"" + escapeJson(apiKey) + "\",\"online\":false}";
            post("/api/plugin/heartbeat", json);
        } catch (Exception e) {
            // Best effort - server is shutting down
        }
    }

    /**
     * Get pending whitelist entries from website
     */
    public String getPendingWhitelist() {
        try {
            return get("/api/plugin/pending-whitelist?apiKey=" + urlEncode(apiKey));
        } catch (Exception e) {
            if (plugin.getConfig().getBoolean("debug", false)) {
                plugin.getLogger().log(Level.WARNING, "Failed to get pending whitelist: " + e.getMessage());
            }
            return null;
        }
    }

    /**
     * Confirm that a player has been added to whitelist in-game
     */
    public boolean confirmWhitelist(String mcUsername) {
        try {
            String json = "{\"apiKey\":\"" + escapeJson(apiKey) + "\",\"mcUsername\":\"" + escapeJson(mcUsername) + "\"}";
            String response = post("/api/plugin/whitelist-confirmed", json);
            return response != null;
        } catch (Exception e) {
            if (plugin.getConfig().getBoolean("debug", false)) {
                plugin.getLogger().log(Level.WARNING, "Failed to confirm whitelist for " + mcUsername + ": " + e.getMessage());
            }
            return false;
        }
    }

    /**
     * Send a player event (join/leave/kick) to website
     */
    public boolean sendPlayerEvent(String event, String playerName, String playerUUID) {
        try {
            String json = "{\"apiKey\":\"" + escapeJson(apiKey) + "\","
                    + "\"event\":\"" + event + "\","
                    + "\"playerName\":\"" + escapeJson(playerName) + "\","
                    + "\"playerUUID\":\"" + escapeJson(playerUUID) + "\"}";

            String response = post("/api/plugin/player-event", json);
            return response != null;
        } catch (Exception e) {
            if (plugin.getConfig().getBoolean("debug", false)) {
                plugin.getLogger().log(Level.WARNING, "Failed to send player event: " + e.getMessage());
            }
            return false;
        }
    }

    // ====== HTTP Methods ======

    /**
     * Send a GET request
     */
    private String get(String path) throws IOException {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(baseUrl + path);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(CONNECT_TIMEOUT);
            conn.setReadTimeout(READ_TIMEOUT);
            conn.setRequestProperty("User-Agent", "MSMPBridge/1.0");

            int code = conn.getResponseCode();
            if (code == 200) {
                return readResponse(conn);
            } else {
                if (plugin.getConfig().getBoolean("debug", false)) {
                    plugin.getLogger().info("GET " + path + " returned " + code);
                }
                return null;
            }
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    /**
     * Send a POST request with JSON body
     */
    private String post(String path, String jsonBody) throws IOException {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(baseUrl + path);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(CONNECT_TIMEOUT);
            conn.setReadTimeout(READ_TIMEOUT);
            conn.setRequestProperty("User-Agent", "MSMPBridge/1.0");
            conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
            conn.setDoOutput(true);

            // Write body
            try (OutputStream os = conn.getOutputStream()) {
                byte[] input = jsonBody.getBytes(StandardCharsets.UTF_8);
                os.write(input, 0, input.length);
            }

            int code = conn.getResponseCode();
            if (code >= 200 && code < 300) {
                return readResponse(conn);
            } else {
                if (plugin.getConfig().getBoolean("debug", false)) {
                    String errorBody = "";
                    try {
                        if (conn.getErrorStream() != null) {
                            BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getErrorStream(), StandardCharsets.UTF_8));
                            StringBuilder sb = new StringBuilder();
                            String line;
                            while ((line = reader.readLine()) != null) sb.append(line);
                            errorBody = sb.toString();
                        }
                    } catch (Exception ignored) {}
                    plugin.getLogger().info("POST " + path + " returned " + code + ": " + errorBody);
                }
                return null;
            }
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    /**
     * Read response body from connection
     */
    private String readResponse(HttpURLConnection conn) throws IOException {
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8))) {
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line);
            }
            return sb.toString();
        }
    }

    /**
     * URL-encode a string
     */
    private String urlEncode(String s) {
        try {
            return java.net.URLEncoder.encode(s, "UTF-8");
        } catch (Exception e) {
            return s;
        }
    }

    /**
     * Escape special characters for JSON strings
     */
    private String escapeJson(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}
