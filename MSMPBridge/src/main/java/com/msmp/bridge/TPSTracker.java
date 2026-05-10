package com.msmp.bridge;

import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;

/**
 * Tracks server TPS (ticks per second) over 1m, 5m, 15m intervals
 * Uses a tick-counting approach: a repeating task runs every second,
 * and another task counts ticks between measurements.
 */
public class TPSTracker {

    private final JavaPlugin plugin;
    private BukkitTask tickTask;
    private BukkitTask sampleTask;
    private volatile int tickCount;
    private volatile long lastSampleTime;

    // Rolling TPS calculations
    private final RollingAverage tps1m = new RollingAverage(60);   // 60 seconds
    private final RollingAverage tps5m = new RollingAverage(300);  // 5 minutes
    private final RollingAverage tps15m = new RollingAverage(900);  // 15 minutes

    public TPSTracker(JavaPlugin plugin) {
        this.plugin = plugin;
    }

    public void start() {
        tickCount = 0;
        lastSampleTime = System.currentTimeMillis();

        // Count ticks (runs every tick = 50ms)
        tickTask = plugin.getServer().getScheduler().runTaskTimer(plugin, () -> {
            tickCount++;
        }, 1L, 1L);

        // Sample TPS every second
        sampleTask = plugin.getServer().getScheduler().runTaskTimer(plugin, () -> {
            long now = System.currentTimeMillis();
            long elapsed = now - lastSampleTime;

            if (elapsed > 0) {
                // ticks per second = (tickCount / elapsed_ms) * 1000
                double tps = (tickCount / (double) elapsed) * 1000.0;
                tps = Math.min(tps, 20.1);

                tps1m.add(tps);
                tps5m.add(tps);
                tps15m.add(tps);
            }

            tickCount = 0;
            lastSampleTime = now;
        }, 20L, 20L); // Start after 1 second, repeat every second
    }

    public void stop() {
        if (tickTask != null) {
            tickTask.cancel();
            tickTask = null;
        }
        if (sampleTask != null) {
            sampleTask.cancel();
            sampleTask = null;
        }
    }

    /**
     * Get current TPS values: [1m, 5m, 15m]
     */
    public double[] getTPS() {
        return new double[]{
                tps1m.getAverage(),
                tps5m.getAverage(),
                tps15m.getAverage()
        };
    }

    /**
     * Simple rolling average calculator
     */
    private static class RollingAverage {
        private final double[] samples;
        private int index = 0;
        private int count = 0;
        private double sum = 0;

        RollingAverage(int size) {
            this.samples = new double[size];
        }

        void add(double value) {
            sum -= samples[index]; // Remove old value
            samples[index] = value;
            sum += value;
            index = (index + 1) % samples.length;
            if (count < samples.length) count++;
        }

        double getAverage() {
            if (count == 0) return 20.0; // Default to 20 TPS
            return Math.min(sum / count, 20.1);
        }
    }
}
