package com.msmp.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.msmp.bridge.commands.MSMPCommand;
import org.bukkit.Bukkit;
import org.bukkit.OfflinePlayer;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerKickEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;

import java.util.UUID;
import java.util.logging.Level;

public class MSMPBridge extends JavaPlugin implements Listener {

    private APIClient apiClient;
    private BukkitTask syncTask;
    private TPSTracker tpsTracker;
    private boolean connected = false;
    private int failedAttempts = 0;
    private static final int MAX_FAILED_ATTEMPTS = 10;
    private final Gson gson = new Gson();

    @Override
    public void onEnable() {
        // Save default config
        saveDefaultConfig();
        reloadConfig();

        // Initialize components
        String websiteUrl = getConfig().getString("website-url", "http://localhost:5000");
        String apiKey = getConfig().getString("api-key", "msmp-plugin-2026");

        apiClient = new APIClient(this, websiteUrl, apiKey);
        tpsTracker = new TPSTracker(this);

        // Register events
        getServer().getPluginManager().registerEvents(this, this);

        // Register commands
        if (getCommand("msmp") != null) {
            getCommand("msmp").setExecutor(new MSMPCommand(this));
        }

        // Start TPS tracker
        tpsTracker.start();

        // Start sync task
        startSyncTask();

        // Initial connection test
        testConnection();

        getLogger().info("MSMPBridge enabled! Connecting to " + websiteUrl);
    }

    @Override
    public void onDisable() {
        // Stop tasks
        if (syncTask != null) {
            syncTask.cancel();
            syncTask = null;
        }
        if (tpsTracker != null) {
            tpsTracker.stop();
        }

        // Notify website that server is shutting down
        if (connected) {
            apiClient.sendServerOffline();
        }

        getLogger().info("MSMPBridge disabled!");
    }

    /**
     * Test connection to the website API
     */
    private void testConnection() {
        Bukkit.getScheduler().runTaskAsynchronously(this, () -> {
            boolean ok = apiClient.testConnection();
            connected = ok;
            if (ok) {
                getLogger().info("Successfully connected to website API!");
                failedAttempts = 0;
                // Do initial sync
                doSync();
            } else {
                getLogger().warning("Failed to connect to website API. Will retry...");
            }
        });
    }

    /**
     * Start the periodic sync task
     */
    private void startSyncTask() {
        int intervalSeconds = getConfig().getInt("sync-interval", 30);
        long intervalTicks = intervalSeconds * 20L;

        syncTask = Bukkit.getScheduler().runTaskTimer(this, () -> {
            Bukkit.getScheduler().runTaskAsynchronously(this, this::doSync);
        }, intervalTicks, intervalTicks);
    }

    /**
     * Perform a full sync cycle
     */
    public void doSync() {
        if (!isEnabled()) return;

        try {
            // Send heartbeat
            if (getConfig().getBoolean("send-heartbeat", true)) {
                boolean heartbeatOk = sendHeartbeat();
                if (!heartbeatOk) {
                    failedAttempts++;
                    if (failedAttempts >= MAX_FAILED_ATTEMPTS) {
                        connected = false;
                        getLogger().warning("Lost connection to website API after " + MAX_FAILED_ATTEMPTS + " failed attempts");
                    }
                    return;
                }
                if (!connected) {
                    connected = true;
                    failedAttempts = 0;
                    getLogger().info("Reconnected to website API!");
                }
            }

            // Pull pending whitelist
            if (getConfig().getBoolean("auto-whitelist", true)) {
                syncWhitelist();
            }

        } catch (Exception e) {
            getLogger().log(Level.WARNING, "Error during sync: " + e.getMessage());
            failedAttempts++;
        }
    }

    /**
     * Send server status heartbeat to website
     */
    private boolean sendHeartbeat() {
        double[] tps = tpsTracker.getTPS();
        StringBuilder playersJson = new StringBuilder("[");
        Player[] onlinePlayers = Bukkit.getOnlinePlayers().toArray(new Player[0]);
        for (int i = 0; i < onlinePlayers.length; i++) {
            Player p = onlinePlayers[i];
            if (i > 0) playersJson.append(",");
            playersJson.append("{\"name\":\"")
                    .append(escapeJson(p.getName()))
                    .append("\",\"uuid\":\"")
                    .append(p.getUniqueId().toString())
                    .append("\"}");
        }
        playersJson.append("]");

        return apiClient.sendHeartbeat(tps, playersJson.toString(), Bukkit.getMaxPlayers());
    }

    /**
     * Sync pending whitelist entries from website using Gson for reliable parsing
     */
    private void syncWhitelist() {
        String response = apiClient.getPendingWhitelist();
        if (response == null || response.isEmpty()) return;

        try {
            JsonObject root = gson.fromJson(response, JsonObject.class);
            if (root == null) return;

            JsonArray players = root.getAsJsonArray("players");
            if (players == null || players.isEmpty()) return;

            for (JsonElement elem : players) {
                JsonObject player = elem.getAsJsonObject();
                String mcUsername = player.has("mcUsername") ? player.get("mcUsername").getAsString() : null;
                String mcUUID = player.has("mcUUID") ? player.get("mcUUID").getAsString() : null;

                if (mcUsername == null || mcUsername.isEmpty()) continue;

                String finalMcUsername = mcUsername;
                String finalMcUUID = mcUUID;
                Bukkit.getScheduler().runTask(this, () -> {
                    addPlayerToWhitelist(finalMcUsername, finalMcUUID);
                });
            }
        } catch (Exception e) {
            getLogger().log(Level.WARNING, "Error parsing whitelist response: " + e.getMessage());
            if (getConfig().getBoolean("debug", false)) {
                getLogger().info("Raw response: " + response);
            }
        }
    }

    /**
     * Add a player to the in-game whitelist
     */
    private void addPlayerToWhitelist(String mcUsername, String mcUUID) {
        try {
            // Try to add by UUID first
            if (mcUUID != null && !mcUUID.isEmpty()) {
                try {
                    UUID uuid = UUID.fromString(mcUUID);
                    OfflinePlayer offlinePlayer = Bukkit.getOfflinePlayer(uuid);
                    if (!offlinePlayer.isWhitelisted()) {
                        offlinePlayer.setWhitelisted(true);
                        getLogger().info("Added " + mcUsername + " (" + mcUUID + ") to whitelist via UUID");
                    }
                } catch (IllegalArgumentException e) {
                    // Invalid UUID format, fall back to name
                    getLogger().warning("Invalid UUID format for " + mcUsername + ": " + mcUUID + ", using name instead");
                    addByName(mcUsername);
                }
            } else {
                addByName(mcUsername);
            }

            // Confirm to website
            Bukkit.getScheduler().runTaskAsynchronously(this, () -> {
                apiClient.confirmWhitelist(mcUsername);
            });

        } catch (Exception e) {
            getLogger().log(Level.WARNING, "Error adding " + mcUsername + " to whitelist: " + e.getMessage());
        }
    }

    private void addByName(String name) {
        OfflinePlayer offlinePlayer = Bukkit.getOfflinePlayer(name);
        if (!offlinePlayer.isWhitelisted()) {
            offlinePlayer.setWhitelisted(true);
            getLogger().info("Added " + name + " to whitelist by name");
        }
    }

    // ====== Event Listeners ======

    @EventHandler(priority = EventPriority.MONITOR)
    public void onPlayerJoin(PlayerJoinEvent event) {
        if (!getConfig().getBoolean("send-player-events", true)) return;
        Player player = event.getPlayer();
        Bukkit.getScheduler().runTaskAsynchronously(this, () -> {
            apiClient.sendPlayerEvent("join", player.getName(), player.getUniqueId().toString());
        });
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onPlayerQuit(PlayerQuitEvent event) {
        if (!getConfig().getBoolean("send-player-events", true)) return;
        Player player = event.getPlayer();
        Bukkit.getScheduler().runTaskAsynchronously(this, () -> {
            apiClient.sendPlayerEvent("leave", player.getName(), player.getUniqueId().toString());
        });
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onPlayerKick(PlayerKickEvent event) {
        if (!getConfig().getBoolean("send-player-events", true)) return;
        Player player = event.getPlayer();
        Bukkit.getScheduler().runTaskAsynchronously(this, () -> {
            apiClient.sendPlayerEvent("kick", player.getName(), player.getUniqueId().toString());
        });
    }

    // ====== Utility Methods ======

    public APIClient getApiClient() {
        return apiClient;
    }

    public TPSTracker getTpsTracker() {
        return tpsTracker;
    }

    public boolean isConnected() {
        return connected;
    }

    /**
     * Escape special characters for JSON strings
     */
    static String escapeJson(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}
