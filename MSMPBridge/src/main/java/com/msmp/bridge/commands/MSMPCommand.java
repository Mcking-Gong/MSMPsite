package com.msmp.bridge.commands;

import com.msmp.bridge.MSMPBridge;
import com.msmp.bridge.APIClient;
import org.bukkit.ChatColor;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;

/**
 * /msmp command handler
 */
public class MSMPCommand implements CommandExecutor {

    private final MSMPBridge plugin;

    public MSMPCommand(MSMPBridge plugin) {
        this.plugin = plugin;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0) {
            sendStatus(sender);
            return true;
        }

        switch (args[0].toLowerCase()) {
            case "sync":
                handleSync(sender);
                break;
            case "status":
                sendStatus(sender);
                break;
            case "reload":
                handleReload(sender);
                break;
            default:
                sender.sendMessage(ChatColor.RED + "Unknown subcommand. Usage: /msmp <sync|status|reload>");
                break;
        }
        return true;
    }

    private void sendStatus(CommandSender sender) {
        sender.sendMessage(ChatColor.GREEN + "===== MSMPBridge Status =====");
        sender.sendMessage(ChatColor.GRAY + "Website: " + ChatColor.WHITE + plugin.getConfig().getString("website-url", "N/A"));
        sender.sendMessage(ChatColor.GRAY + "Connected: " + (plugin.isConnected() ? ChatColor.GREEN + "Yes" : ChatColor.RED + "No"));
        sender.sendMessage(ChatColor.GRAY + "Auto-whitelist: " + ChatColor.WHITE + plugin.getConfig().getBoolean("auto-whitelist", true));
        sender.sendMessage(ChatColor.GRAY + "Send events: " + ChatColor.WHITE + plugin.getConfig().getBoolean("send-player-events", true));
        sender.sendMessage(ChatColor.GRAY + "Sync interval: " + ChatColor.WHITE + plugin.getConfig().getInt("sync-interval", 30) + "s");

        double[] tps = plugin.getTpsTracker().getTPS();
        sender.sendMessage(ChatColor.GRAY + "TPS (1m/5m/15m): " + ChatColor.WHITE +
                String.format("%.1f", tps[0]) + " / " +
                String.format("%.1f", tps[1]) + " / " +
                String.format("%.1f", tps[2]));

        sender.sendMessage(ChatColor.GRAY + "Online players: " + ChatColor.WHITE +
                plugin.getServer().getOnlinePlayers().size() + " / " + plugin.getServer().getMaxPlayers());
    }

    private void handleSync(CommandSender sender) {
        sender.sendMessage(ChatColor.YELLOW + "Starting manual sync...");
        plugin.getServer().getScheduler().runTaskAsynchronously(plugin, () -> {
            plugin.doSync();
            plugin.getServer().getScheduler().runTask(plugin, () -> {
                if (plugin.isConnected()) {
                    sender.sendMessage(ChatColor.GREEN + "Sync completed successfully!");
                } else {
                    sender.sendMessage(ChatColor.RED + "Sync failed - cannot connect to website API");
                }
            });
        });
    }

    private void handleReload(CommandSender sender) {
        plugin.reloadConfig();
        sender.sendMessage(ChatColor.GREEN + "MSMPBridge config reloaded!");
        sender.sendMessage(ChatColor.GRAY + "Note: Some changes may require a server restart to take effect.");
    }
}
